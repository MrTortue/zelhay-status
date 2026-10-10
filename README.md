# Zelhay Host — Page de status & preuve de disponibilité

**Page publique : https://mrtortue.github.io/zelhay-status/**

Ce dépôt est notre engagement de transparence envers vous, nos clients. Il héberge
une supervision **indépendante** de nos services et publie, en continu, l'état et la
disponibilité réelle de notre infrastructure.

## Pourquoi cette page ?

Un hébergeur qui mesure lui-même sa disponibilité est juge et partie. Nous avons donc
choisi de faire mesurer nos services **depuis l'extérieur**, par une plateforme que
nous ne contrôlons pas (GitHub), avec des résultats que **personne ne peut modifier
après coup** — pas même nous.

Vous pouvez ainsi :

- vérifier à tout moment si nos services répondent ;
- consulter notre disponibilité sur 24 h, 7 jours, 30 jours et 90 jours ;
- consulter l'historique complet des incidents, avec heure de début, de fin et durée ;
- constater que notre engagement de disponibilité (**objectif : 99,9 %**) est tenu.

## Ce que nous surveillons

| Service | Ce qui est vérifié |
|---|---|
| `zelhay-host.fr` | Réponse HTTPS du site, validité du certificat TLS |
| `web.zelhay-host.fr` | Réponse HTTPS, certificat TLS |
| `game.zelhay-host.fr` | Réponse HTTPS, certificat TLS |
| `console.zelhay-host.fr` | Réponse HTTPS, certificat TLS |
| Serveurs eu-pa5 (5 machines) | Joignabilité réseau (ICMP ou port TCP ouvert) |

## Comment la mesure est faite

- **Toutes les 5 minutes**, une sonde s'exécute sur les serveurs de GitHub (hors de
  notre infrastructure) et teste chaque service.
- Chaque résultat est **enregistré dans ce dépôt git**, horodaté et signé par GitHub :
  l'historique est public, auditable et non falsifiable.
- **Disponibilité** = nombre de tests réussis ÷ nombre de tests effectués, par service,
  sur la période affichée. La valeur globale est la moyenne de tous les services.
- Un test échoué est **réessayé deux fois** (après 3 s puis 10 s) pour écarter les erreurs passagères.
  Un service est déclaré **en panne** après 2 échecs consécutifs ; un échec isolé est
  affiché comme « dégradé ».
- Chaque panne ouvre automatiquement un **incident** daté, clos automatiquement au
  retour du service. Ces incidents sont visibles sur la page de status.

## Ce que cette page ne mesure pas

- Les performances internes d'un serveur (CPU, mémoire, disque).
- Les services spécifiques à votre compte (un serveur de jeu, une boîte mail, …).
- La disponibilité vue depuis votre propre connexion Internet.

La sonde tourne depuis les États-Unis : les temps de réponse affichés incluent la
traversée de l'Atlantique et sont donc supérieurs à ceux constatés depuis la France.

## Transparence totale

Tout est ouvert dans ce dépôt :

- `targets.yml` — la liste exacte des services surveillés et comment ;
- `probe/probe.py` — le programme de test, ligne par ligne ;
- `data/` — l'intégralité des mesures brutes, à chaque passage, depuis le début ;
- `.github/workflows/status.yml` — l'automatisation qui exécute tout cela.

Vous pouvez vérifier vous-même chaque chiffre affiché à partir de ces fichiers.

## Une question ?

Pour toute question sur un incident ou sur cette page, contactez-nous via votre espace
client ou par e-mail. Si vous constatez un problème que la page n'affiche pas,
signalez-le-nous : nous ajusterons la supervision.
