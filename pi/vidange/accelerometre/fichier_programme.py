"""Le fichier du programme du RP2040 de l'accéléromètre (tâche 16).

« accelerometre.bin » = la fiche du programme (256 octets : taille, contrôle CRC-32, nom), puis
le programme. C'est ce que le Pi envoie au chargeur du RP2040 par le fil série, et ce qu'il garde
en copie avant une mise à jour. Format : `accelerometre/src/fiche.h`.

« accelerometre-complet.uf2 » = le chargeur, la fiche et le programme, à copier sur le disque
RPI-RP2 du RP2040 par l'USB (première installation à l'établi, ou secours).

Lancé par CMake quand on fabrique le programme (`accelerometre/CMakeLists.txt`) :

    python -m vidange.accelerometre.fichier_programme --chargeur chargeur.bin
        --programme programme.bin --adresse-flash 0x10000000 --adresse-fiche 0x10008000
        --adresse-programme 0x10009000 --depot accelerometre
        --sortie-bin accelerometre.bin --sortie-uf2 accelerometre-complet.uf2

Seule la bibliothèque standard de Python sert ici (la fabrication n'a que pydantic et PyYAML).
"""

import argparse
import re
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

FICHE_TAILLE = 256
MAGIE = b"ACCL"
FORMAT = 1
NOM_MAX = 31
NOM_VALIDE = re.compile(r"^[A-Za-z0-9._+-]{1,31}$")
# magie, format, adresse, taille, crc, nom (accelerometre/src/fiche.h)
_DEBUT_FICHE = struct.Struct("<4sIIII32s")

# UF2 (format du disque RPI-RP2) : blocs de 512 octets portant 256 octets chacun.
UF2_MAGIE_1 = 0x0A324655
UF2_MAGIE_2 = 0x9E5D5157
UF2_MAGIE_FIN = 0x0AB16F30
UF2_AVEC_FAMILLE = 0x00002000
UF2_FAMILLE_RP2040 = 0xE48BFF56
UF2_PAGE = 256


class ErreurFichier(Exception):
    """Un fichier de programme mal formé (avec la raison, en clair)."""


def crc32(octets: bytes) -> int:
    return zlib.crc32(octets) & 0xFFFFFFFF


@dataclass(frozen=True)
class Fiche:
    adresse: int  # où le programme a été fabriqué pour tourner
    taille: int
    crc: int
    nom: str

    def octets(self) -> bytes:
        if not NOM_VALIDE.match(self.nom):
            raise ErreurFichier(f"nom de programme refusé « {self.nom} »")
        debut = _DEBUT_FICHE.pack(
            MAGIE, FORMAT, self.adresse, self.taille, self.crc, self.nom.encode("ascii")
        )
        debut += bytes(FICHE_TAILLE - 4 - len(debut))
        return debut + struct.pack("<I", crc32(debut))

    @classmethod
    def lire(cls, octets: bytes) -> "Fiche":
        if len(octets) < FICHE_TAILLE or octets[:4] != MAGIE:
            raise ErreurFichier("ce n'est pas un programme de l'accéléromètre (fiche absente)")
        fiche = octets[:FICHE_TAILLE]
        (controle,) = struct.unpack("<I", fiche[-4:])
        if crc32(fiche[:-4]) != controle:
            raise ErreurFichier("fiche du programme abîmée (contrôle faux)")
        _, format_, adresse, taille, crc, nom = _DEBUT_FICHE.unpack(fiche[: _DEBUT_FICHE.size])
        if format_ != FORMAT:
            raise ErreurFichier(f"format de fiche {format_} inconnu (attendu : {FORMAT})")
        texte = nom.split(b"\0", 1)[0].decode("ascii", errors="replace")
        if not NOM_VALIDE.match(texte):
            raise ErreurFichier(f"nom de programme mal écrit dans la fiche « {texte} »")
        return cls(adresse, taille, crc, texte)


def est_programme_accelerometre(contenu: bytes) -> bool:
    """Le fichier commence-t-il comme un programme de l'accéléromètre ?"""
    return contenu[:4] == MAGIE


def assembler(programme: bytes, adresse: int, nom: str) -> bytes:
    """Le fichier .bin : la fiche puis le programme."""
    if not programme:
        raise ErreurFichier("programme vide")
    return Fiche(adresse, len(programme), crc32(programme), nom).octets() + programme


def lire_fichier(contenu: bytes) -> tuple[Fiche, bytes]:
    """La fiche et le programme d'un fichier .bin, vérifiés (ErreurFichier sinon)."""
    fiche = Fiche.lire(contenu)
    programme = contenu[FICHE_TAILLE:]
    if len(programme) != fiche.taille:
        raise ErreurFichier(
            f"fichier coupé ou trop long : {len(programme)} octets de programme au lieu de "
            f"{fiche.taille}"
        )
    if crc32(programme) != fiche.crc:
        raise ErreurFichier("programme abîmé (contrôle faux)")
    return fiche, programme


def uf2(morceaux: list[tuple[int, bytes]]) -> bytes:
    """Un fichier UF2 pour le RP2040 avec ces morceaux (adresse, octets) de la flash."""
    pages: list[tuple[int, bytes]] = []
    for adresse, octets in morceaux:
        if adresse % UF2_PAGE:
            raise ErreurFichier(f"adresse {adresse:#x} pas au début d'une page de 256 octets")
        for debut in range(0, len(octets), UF2_PAGE):
            page = octets[debut : debut + UF2_PAGE]
            pages.append((adresse + debut, page + b"\xff" * (UF2_PAGE - len(page))))
    blocs = []
    for numero, (adresse, page) in enumerate(pages):
        entete = struct.pack(
            "<IIIIIIII",
            UF2_MAGIE_1,
            UF2_MAGIE_2,
            UF2_AVEC_FAMILLE,
            adresse,
            UF2_PAGE,
            numero,
            len(pages),
            UF2_FAMILLE_RP2040,
        )
        donnees = page + bytes(476 - UF2_PAGE)
        blocs.append(entete + donnees + struct.pack("<I", UF2_MAGIE_FIN))
    return b"".join(blocs)


def nom_de_version(depot: Path) -> str:
    """Le nom du programme : le commit Git du dépôt (« -modifie » s'il a des changements)."""
    try:
        fini = subprocess.run(
            ["git", "describe", "--always", "--dirty=-modifie", "--abbrev=7", "--exclude=*"],
            cwd=depot,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "inconnu"
    nom = fini.stdout.strip()
    return nom if fini.returncode == 0 and NOM_VALIDE.match(nom) else "inconnu"


def fabriquer(options: argparse.Namespace) -> None:
    chargeur = Path(options.chargeur).read_bytes()
    programme = Path(options.programme).read_bytes()
    taille_chargeur = options.adresse_fiche - options.adresse_flash
    if len(chargeur) > taille_chargeur:
        raise ErreurFichier(
            f"le chargeur ({len(chargeur)} octets) ne tient pas dans sa place "
            f"({taille_chargeur} octets)"
        )
    nom = options.nom or nom_de_version(Path(options.depot))
    fichier = assembler(programme, options.adresse_programme, nom)
    Path(options.sortie_bin).write_bytes(fichier)
    Path(options.sortie_uf2).write_bytes(
        uf2(
            [
                (options.adresse_flash, chargeur),
                (options.adresse_fiche, fichier[:FICHE_TAILLE]),
                (options.adresse_programme, programme),
            ]
        )
    )
    print(
        f"Programme « {nom} » : {len(programme)} octets, contrôle {crc32(programme):08X} ; "
        f"chargeur : {len(chargeur)} octets sur {taille_chargeur}"
    )


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(
        prog="python -m vidange.accelerometre.fichier_programme",
        description="Fabrique accelerometre.bin et accelerometre-complet.uf2.",
    )
    for nom in ("--chargeur", "--programme", "--sortie-bin", "--sortie-uf2"):
        lecteur.add_argument(nom, required=True)
    for nom in ("--adresse-flash", "--adresse-fiche", "--adresse-programme"):
        lecteur.add_argument(nom, required=True, type=lambda texte: int(texte, 0))
    lecteur.add_argument("--depot", default=".", help="dossier Git (pour le nom du programme)")
    lecteur.add_argument("--nom", help="nom du programme (défaut : le commit Git)")
    options = lecteur.parse_args(arguments)
    try:
        fabriquer(options)
    except (OSError, ErreurFichier) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
