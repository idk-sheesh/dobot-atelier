# Historique des versions

## 1.3.0 - 2026-08-29

- chemin de `DobotServer.exe` configurable dans Diagnostic COM et mémorisé ;
- blocage de toute commande avec télémétrie absente, ancienne ou angle initial hors limites ;
- indicateur visible `INITIALISATION OK` / `MOUVEMENT BLOQUÉ` avec angle J2 ;
- procédure de démarrage V1 intégrée : pose sûre, alimentation 12 V 5 A, USB puis RESET ;
- test diagnostic J1 configuré comme le client officiel et porté à 50 % pendant 0,30 s ;
- détection du DobotClient officiel pour empêcher un double pilotage du serveur.

## 1.2.3 - 2026-08-20

- suppression de l'état `MachineIdle` de l'arrêt d'urgence, susceptible de verrouiller les drivers FPGA V1 ;
- arrêt aligné sur le client officiel avec états Jog au repos ;
- extinction explicite de la pompe et du laser sans désactiver les moteurs.

## 1.2.2 - 2026-08-20

- arrêt automatique du DobotServer lancé par Dobot Atelier lors de la fermeture ;
- nettoyage du serveur si la tentative de connexion échoue ;
- suppression du conflit de port 5555 avec le client officiel après fermeture de l'application.

## 1.2.1 - 2026-08-20

- configuration des limites physiques Playback exigées par le contrôleur V1 avant chaque trajectoire ;
- test moteur J1 court confirmant un déplacement réel plutôt qu'une simple connexion TCP ;
- arrêt automatique après 3,5 secondes sans mouvement mesuré ;
- fin de trajectoire déclarée seulement après confirmation de la position finale.

## 1.2.0 - 2026-08-20

- diagnostic COM intégré avec ports, trames, commandes, file et acquittement ;
- test de communication sans mouvement ;
- envoi immédiat des réglages avant le premier point de trajectoire ;
- gabarit d'essai réduit à 40 mm pour rester près de la position courante.

## 1.1.4 - 2026-08-20

- envoi immédiat de la première commande d'une trajectoire ;
- correction du démarrage bloqué lorsque le firmware est silencieux au repos ;
- libellés séparant clairement l'aperçu du mouvement réel ;
- état d'exécution visible au-dessus de l'aperçu.

## 1.1.3 - 2026-08-20

- réveil sans mouvement de la télémétrie au démarrage ;
- nouvelles tentatives automatiques lorsque le serveur est connecté mais silencieux.

## 1.1.2 - 2026-08-20

- blocage des ouvertures multiples de Dobot Atelier ;
- suppression du conflit de télémétrie causé par la limite à un client du serveur V1.

## 1.1.1 - 2026-08-20

- badge permanent indiquant clairement l'état du robot ;
- distinction entre serveur connecté et coordonnées réellement reçues.

## 1.1.0 - 2026-08-20

- interface latérale compacte et défilable ;
- boutons principaux visibles avec la mise à l'échelle Windows ;
- affichage des coordonnées lissé à 20 Hz ;
- arrêt prioritaire renforcé et délai TCP désactivé ;
- ajout du numéro de version visible.

## 1.0.0 - 2026-08-20

- première version de Dobot Atelier ;
- import et aperçu SVG ;
- modes simulation, stylo et laser ;
- calibration X/Y/Z, limites de sécurité et arrêt laser.
