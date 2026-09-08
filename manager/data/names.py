"""Name and identity pools for the fictional world.

All names are invented combinations from the pools below. The game is set in
the fictional federation of Valland and its fictional neighbouring nations.
"""

FIRST_NAMES = [
    "Adem", "Alaric", "Aldous", "Basil", "Casper", "Cian", "Desmond", "Dorian",
    "Edvard", "Elias", "Finnian", "Garet", "Hale", "Ivor", "Jannik", "Kellan",
    "Leander", "Malik", "Nedram", "Orin", "Pierce", "Quillan", "Rowan", "Silas",
    "Toren", "Ulf", "Varek", "Wendel", "Yonas", "Zeph", "Arden", "Bram",
    "Cody", "Dante", "Emrys", "Ferenc", "Gustav", "Herman", "Idris", "Jareth",
    "Kofi", "Lorcan", "Marek", "Niall", "Oskar", "Petros", "Quentin", "Rasmus",
    "Sander", "Torben", "Ugo", "Valen", "Willem", "Xander", "Yusuf", "Zander",
    "Anders", "Brogan", "Callum", "Darrow", "Ewan", "Fletcher", "Gawain",
]

LAST_NAMES = [
    "Alcott", "Barlow", "Castellan", "Davenport", "Ellery", "Fairfax", "Grayson",
    "Hawthorne", "Isenhart", "Jarvis", "Keller", "Lanchester", "Merrick",
    "Nightingale", "Osgood", "Pemberton", "Quigley", "Rathbone", "Stirling",
    "Talbot", "Underwood", "Vane", "Warwick", "Yates", "Beckett", "Caldwell",
    "Donovan", "Everett", "Fenwick", "Galloway", "Hartley", "Ingram", "Jensen",
    "Kingsley", "Larkin", "Maddox", "Nash", "Ortiz", "Parker", "Quinn",
    "Reed", "Sheffield", "Tatum", "Upton", "Vance", "Whitmore", "Ellison",
    "Croft", "Darby", "Ellwood", "Farrier", "Grimshaw", "Harlan", "Ivy",
    "Jessop", "Kendrick", "Lowe", "Marrow", "Nex", "Odel", "Pryce", "Rourke",
]

# real-world footballing nations; keep weights aligned with NATIONS order.
NATIONS = [
    "France", "Spain", "Tunisia", "England", "Germany",
    "Netherlands", "Italy", "Argentina", "Brazil", "Portugal",
]

NATION_WEIGHTS = [0.20, 0.15, 0.05, 0.25, 0.10, 0.07, 0.05, 0.05, 0.05, 0.03]

POSITION_POOLS = {
    "GK": ["GK"],
    "CB": ["CB", "RB", "LB"],
    "FB": ["LB", "RB", "WB"],
    "DM": ["DM", "CM"],
    "CM": ["CM", "DM", "AM"],
    "AM": ["AM", "CM", "LW"],
    "W": ["LW", "RW", "LM", "RM"],
    "ST": ["ST", "CF"],
}

ALT_POSITION_WEIGHT = 0.4


def nationality(rng, stream: str = "names") -> str:
    return rng.choices(NATIONS, weights=NATION_WEIGHTS, k=1, stream=stream)[0]


def full_name(rng, stream: str = "names") -> tuple[str, str]:
    first = rng.choice(FIRST_NAMES, stream=stream)
    last = rng.choice(LAST_NAMES, stream=stream)
    return first, last