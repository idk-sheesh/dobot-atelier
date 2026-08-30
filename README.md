# Dobot Atelier

Version actuelle : **1.3.0**

Interface Windows pour le Dobot V1.0 Kickstarter utilisant le serveur officiel
`DobotServer.exe` sur `127.0.0.1:5555`.

## Fonctions

- import SVG (`path`, `line`, `polyline`, `polygon`, `rect`, `circle`, `ellipse`) ;
- aperçu du tracé et des déplacements entre formes ;
- réglage de l'échelle, de l'origine, de la rotation et des hauteurs Z ;
- simulation outil éteint ;
- modes stylo et laser ;
- limites absolues X/Y/Z ;
- arrêt immédiat avec vidage de la file et extinction du laser.
- verrouillage des mouvements si la télémétrie est absente ou si un joint démarre hors limites ;
- contrôle visible de l’initialisation et procédure RESET du Dobot V1 ;
- détection du DobotClient officiel pour éviter deux logiciels de pilotage.

## Utilisation sûre

1. Positionner J2 entre 70° et 82°, brancher le 12 V 5 A puis l’USB, et appuyer sur RESET.
2. Fermer l'ancien `DobotClient` : un seul logiciel doit piloter le robot.
3. Lancer `Dobot Atelier` et attendre `INITIALISATION OK`.
4. Charger un SVG et choisir `Simulation`.
5. Placer manuellement l'outil au point d'origine, puis cliquer sur
   `Prendre la position actuelle`.
6. Régler `Z travail` et `Z dégagé`, puis faire une simulation lente.
7. Choisir `Stylo` ou `Laser` seulement après validation du trajet.

Le laser doit être utilisé dans une enceinte fermée, avec extraction des fumées et
protection adaptée à sa longueur d'onde. Ne jamais graver de PVC, vinyle, matière
inconnue ou surface réfléchissante.

Les textes SVG doivent être convertis en chemins dans le logiciel de dessin avant
l'import.
