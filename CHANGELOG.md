# Historique des versions

## 1.6.2 - 2026-10-28

- synchronisation du dépôt public avec les correctifs 1.4 à 1.6.1, sans réintroduire le JOG continu ;
- conservation du choix de DobotServer.exe, y compris à côté de l'exécutable empaqueté ;
- fermeture et nettoyage de l'ancienne connexion avant reconnexion, sans reprise de file ;
- rejet des mesures non finies et contrôle du verrou juste avant un envoi de commande en file ;
- refus des chemins SVG incomplets, des coordonnées non finies et du rééchantillonnage démesuré ;
- fin de trajectoire basée sur de nouveaux paquets, sans prétendre confirmer un mouvement physique ;
- mode « Simulation » renommé « Déplacement sans outil » et refus des modes inconnus ;
- conservation du point d'outil pendant un déplacement sans outil et extinction explicite de la pompe et du laser avant une trajectoire ;
- verrou d'essai enregistré avant le premier envoi, pour conserver la trace en cas d'interruption ;
- README de présentation, installation et limites de validation documentées ;
- ouverture `--offline` sans lancement du serveur ni connexion au robot ;
- tests Windows/Linux et builds Windows marqués comme préversions. Aucun nouvel essai matériel : le défaut moteur reste ouvert.

## 1.6.1 - 2026-10-14

- correction de l'essai linéaire : MOVL = 2 dans le code du client DobotTools V1.0 installé, contrairement à la table du PDF 2017 utilisée en 1.6.0 ;
- retrait du message ambigu « Pas terminé » : une cible annoncée par le contrôleur ne confirme pas un mouvement physique ;
- rapport explicite `telemetry_target_reached`, sans indicateur de réussite physique ;
- conservation du verrou de l'essai après redémarrage lorsqu'un rapport existe ;
- aucun nouvel essai moteur effectué pour cette mise à jour. L'absence de mouvement observée reste à diagnostiquer.

## 1.6.0 - 2026-10-14

- diagnostic limité à une seule cible de 1 mm vers la base, à hauteur constante, sans JOG continu ;
- validation nominale du segment et des marges articulaires avant l'envoi ;
- réglages lents sans changement de point d'outil, contrôle de stabilité avant mouvement, suivi et arrêt avec verrouillage ;
- résultat enregistré en distinguant la position reçue d'une mesure physique indépendante ;
- changement erroné du commentaire des modes V1 d'après le PDF 2017 ; corrigé en 1.6.1 selon le client V1.0 installé.

## 1.5.0 - 2026-10-01

- carte des points XY mesurés à la règle sur un plateau à hauteur fixe, indépendamment du robot et sans commande moteur ;
- séparation des mesures du plateau et des relevés articulaires, avec avertissement sur les espaces non mesurés ;
- sauvegarde atomique des mesures, rechargement validé et archivage lors d'un changement de plateau ;
- retrait du bouton appliquant les extrêmes X/Y/Z comme zone de mouvement ;
- voyant de connexion non vert lorsque les paquets de télémétrie sont anciens ;
- conservation des deux anciens relevés depuis les plages affichées en 1.4.3 (précision de 0,1).

## 1.4.3 - 2026-09-30

- ajout de l'étape RESET physique après remise du 12 V, confirmée nécessaire sur le robot pour relire J2/J3 ;
- rappel de cette étape lorsque les coordonnées restent identiques après déplacement manuel ;
- précision du périmètre des relevés : J2/J3 à orientation de base constante, sans validation de tout le volume X/Y/Z.

## 1.4.2 - 2026-09-30

- correction du blocage de la première position, comparée par erreur à la pose présente à l'ouverture de la cartographie ;
- doublons ignorés sans alerte de panne et affichage des coordonnées courantes dans la fenêtre ;
- conservation de l'affichage des points lors de la réouverture de la fenêtre ;
- refus des mesures sans connexion active, sans télémétrie récente ou contenant des valeurs non finies.

## 1.4.1 - 2026-09-29

- remplacement de la mesure continue USB seul, non prise en charge par cette carte V1, par des relevés position par position ;
- contrôle de fraîcheur de la télémétrie et refus des relevés identiques ;
- procédure affichée : déplacement manuel 12 V coupé, mains écartées puis 12 V remis uniquement pour relever la pose.

## 1.4.0 - 2026-09-29

- retrait de tous les tests JOG continus après constat d'un arrêt tardif sur le contrôleur V1 ;
- arrêt renforcé par cinq trames `AxisIdle` séparées et verrouillage de l'ancienne file ;
- surveillance des quatre angles pendant toute trajectoire, avec arrêt à moins de 3 degrés d'une limite ;
- cartographie manuelle moteurs hors tension des plages X/Y/Z et J1-J4, puis application d'une marge de 5 mm.

## 1.3.1 - 2026-09-28

- simulation à hauteur constante : suppression des mouvements JUMP entre tracés ;
- conservation de l'orientation R courante pendant l'essai ;
- préparation d'un essai de 10 mm centré, avec contrôle de proximité et marge initiale de 5 degrés ;
- affichage J1/J2/J3/J4 et impulsions de réglage J2/J3 de 0,25 s avec arrêt sur un timer indépendant de l'interface.

## 1.3.0 - 2026-08-29

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
