# Gestion de Portefeuille et Contrôle du Risque PEA

## Principes de Construction du Portefeuille

### Diversification efficiente
La diversification réduit le risque spécifique (propre à une entreprise) sans réduire le rendement espéré. Empiriquement, le bénéfice de diversification marginal diminue au-delà de 15-20 positions en actions individuelles. Au-delà de 30 positions, on réplique quasiment un indice avec les inconvénients du stock picking (frais, temps d'analyse).

Recommandation PEA : 5-15 actions individuelles pour le satellite + 1-3 ETF pour le core. Total : 8-18 lignes maximum.

### Sizing des positions
Deux approches complémentaires :
- Equal weight : chaque position a le même poids initial (ex : 10 positions = 10 % chacune). Simple, réduit le risque de concentration. Adapté aux débutants.
- Risk parity : pondérer inversement à la volatilité. Une action avec un bêta de 1.5 reçoit un poids plus faible qu'une action avec un bêta de 0.7. Formule simplifiée : poids_i = (1 / volatilité_i) / somme(1 / volatilité_j).

Dans les deux cas, ne jamais dépasser 10 % sur une action individuelle et 25 % sur un secteur.

### Rééquilibrage
Fréquence recommandée : semestrielle ou annuelle. Le rééquilibrage consiste à revendre les positions qui ont trop monté (surpondérées) et à renforcer celles qui ont baissé (sous-pondérées) pour revenir aux poids cibles. C'est un mécanisme contra-cyclique naturel : il force à vendre haut et acheter bas.

Seuil de déclenchement alternatif : rééquilibrer quand une position dévie de plus de 5 points de pourcentage de son poids cible (ex : cible 10 %, rééquilibrer si > 15 % ou < 5 %).

## Gestion du Risque

### Stop-loss et PEA
Le stop-loss classique (vente automatique sous un certain prix) est moins pertinent sur le PEA avec horizon long terme. Les corrections de 10-20 % sont fréquentes et ne remettent pas en cause la thèse d'investissement. Un stop-loss trop serré peut entraîner des ventes inutiles suivies de rebonds (whipsaw).

Alternative recommandée : stop-loss fondamental. Au lieu d'un seuil de prix, définir des critères fondamentaux de sortie : coupe du dividende, dégradation du bilan (dette/EBITDA > seuil), perte de l'avantage compétitif, changement structurel du secteur. Si un de ces critères est atteint, vendre indépendamment du prix.

### Drawdown et tolérance au risque
Un portefeuille 100 % actions peut subir des drawdowns de 40-60 % (crise 2008 : -57 % pour le CAC 40, crise 2020 : -38 %). L'investisseur doit être psychologiquement préparé à ces baisses.

Règle simple pour calibrer l'exposition : le pourcentage d'actions dans le portefeuille global (PEA + autres placements) ne devrait pas dépasser le drawdown maximal qu'on est prêt à supporter × 2. Exemple : si on supporte max 25 % de perte, ne pas dépasser 50 % d'actions.

Dans le PEA spécifiquement, le portefeuille est par définition 100 % actions/ETF actions. Le contrôle du risque se fait par la diversification et la qualité des titres sélectionnés, pas par l'allocation entre classes d'actifs.

### Corrélation et diversification réelle
Deux actions du même secteur (ex : BNP Paribas + Société Générale) n'apportent pas de diversification réelle car elles sont très corrélées. La vraie diversification vient de la combinaison de secteurs à faible corrélation.

Paires historiquement peu corrélées sur Euronext : Énergie + Technologie, Santé + Automobile, Utilities + Luxe, Finance + Consommation de base.

En période de crise, toutes les corrélations convergent vers 1 (tout baisse ensemble). C'est pourquoi la diversification protège contre les risques spécifiques mais pas contre les crises systémiques. Seul le cash ou les obligations (hors PEA) protègent contre le risque systémique.

## Suivi et Reporting du Portefeuille

### Métriques à suivre
- Performance totale : plus-value latente + dividendes perçus (Total Return).
- Performance vs benchmark : comparer au STOXX 600 ou MSCI World. Si le portefeuille sous-performe l'indice sur 3 ans+, questionner la stratégie de stock picking.
- Rendement en dividendes : dividendes annuels perçus / capital investi.
- Exposition sectorielle : répartition en % par secteur, vérifier qu'aucun secteur ne dépasse 25 %.
- Exposition géographique : répartition par pays du siège social.
- Volatilité du portefeuille : écart-type des rendements hebdomadaires ou mensuels.
- Max drawdown : plus grande perte depuis un sommet.

### Fréquence de suivi
Un suivi quotidien n'est pas nécessaire et peut être contre-productif (incite au trading excessif). Recommandation : consulter les cours 1 fois par semaine, faire une revue approfondie 1 fois par mois, rééquilibrer 1-2 fois par an.

Exception : en période de forte volatilité (VIX > 30, indices en correction > 10 %), un suivi plus fréquent est justifié pour identifier des opportunités d'achat (DCA renforcé).

## Psychologie de l'Investisseur

### Biais cognitifs à connaître
- Biais de confirmation : ne chercher que les informations qui confirment sa thèse d'investissement. Solution : lire activement les thèses bearish sur ses positions.
- Aversion à la perte : la douleur d'une perte de 1 000 € est psychologiquement 2x plus forte que le plaisir d'un gain de 1 000 €. Conséquence : on vend les gagnants trop tôt et on garde les perdants trop longtemps (disposition effect).
- Ancrage : se focaliser sur son prix d'achat comme référence. Le marché ne sait pas à quel prix on a acheté. La seule question pertinente : au prix actuel, est-ce que j'achèterais cette action aujourd'hui ?
- FOMO (Fear of Missing Out) : acheter une action parce qu'elle a monté de 80 % et qu'on a peur de rater la suite. C'est généralement le pire moment pour acheter.
- Excès de confiance : surestimer sa capacité à battre le marché. Rappel : sur 10 ans, 85-90 % des gérants professionnels sous-performent leur indice de référence.

### Discipline et plan d'investissement
Écrire un plan d'investissement avec des règles claires : montant mensuel DCA, critères d'achat, critères de vente, poids max par position, rééquilibrage semestriel. Suivre le plan mécaniquement, sans déroger sous l'effet des émotions.

VEGAS peut aider à maintenir cette discipline en objectivant les décisions : métriques factuelles, comparaison au benchmark, alertes sur les déviations par rapport au plan.
