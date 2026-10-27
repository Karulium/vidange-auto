"""Découpe d'une vidéo « MJPEG » (des images JPEG à la suite) en images entières.

Une image JPEG commence par FF D8 et finit par FF D9. On ne cherche pas bêtement FF D9 : une
image peut en contenir une plus petite (vignette dans ses informations). On suit donc ses
morceaux (chacun dit sa longueur) jusqu'aux données de l'image, où FF D9 ne peut plus
apparaître que pour dire « fin ».
"""

DEBUT = b"\xff\xd8"
FIN = 0xD9
DONNEES = 0xDA  # morceau suivi des données de l'image (« SOS »)


def _fin_image(tampon: bytearray) -> int | None:
    """Où finit l'image qui commence au début du tampon : None si elle n'est pas encore
    toute arrivée, -1 si elle est abîmée."""
    i = len(DEBUT)
    while True:
        if i + 1 >= len(tampon):
            return None
        if tampon[i] != 0xFF:
            return -1
        marqueur = tampon[i + 1]
        if marqueur == 0xFF:  # octet de remplissage
            i += 1
            continue
        if marqueur == FIN:
            return i + 2
        if 0xD0 <= marqueur <= 0xD7 or marqueur == 0x01:  # marqueurs sans longueur
            i += 2
            continue
        if i + 4 > len(tampon):
            return None
        longueur = int.from_bytes(tampon[i + 2 : i + 4], "big")
        if longueur < 2:
            return -1
        i += 2 + longueur
        if marqueur != DONNEES:
            continue
        # Données de l'image : FF y est toujours suivi de 00 (ou d'un repère D0 à D7),
        # sauf pour un vrai marqueur : la fin, ou un nouveau morceau (JPEG progressif).
        while True:
            k = tampon.find(b"\xff", i)
            if k < 0 or k + 1 >= len(tampon):
                return None
            suivant = tampon[k + 1]
            if suivant == 0x00 or suivant == 0xFF or 0xD0 <= suivant <= 0xD7:
                i = k + 1
                continue
            i = k
            break


class Decoupeur:
    """On lui donne la vidéo morceau par morceau, il rend les images entières."""

    def __init__(self, taille_max: int = 20 * 1024 * 1024) -> None:
        # Une « image » plus grosse que ça est un flux abîmé : on la jette.
        self.taille_max = taille_max
        self._tampon = bytearray()
        self.abimees = 0

    def ajouter(self, donnees: bytes) -> list[bytes]:
        self._tampon += donnees
        images = []
        while True:
            debut = self._tampon.find(DEBUT)
            if debut < 0:
                # Garder le dernier octet : il peut être le FF d'un début coupé en deux.
                del self._tampon[:-1]
                return images
            del self._tampon[:debut]
            fin = _fin_image(self._tampon)
            if fin is None:
                if len(self._tampon) > self.taille_max:
                    self.abimees += 1
                    del self._tampon[: len(DEBUT)]
                    continue
                return images
            if fin < 0:
                self.abimees += 1
                del self._tampon[: len(DEBUT)]
                continue
            images.append(bytes(self._tampon[:fin]))
            del self._tampon[:fin]
