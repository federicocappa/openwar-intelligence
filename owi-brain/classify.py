"""Classificazione ruolo/nazione di un velivolo militare.

Ordine: codice tipo ICAO (t) -> prefisso callsign -> range hex.
Ruoli: fighter, bomber, tanker, awacs, isr, transport, helicopter, trainer, vip, unknown.
"""

ROLE_BY_TYPE = {
    # tanker
    "K35R": "tanker", "K35E": "tanker", "KC46": "tanker", "K46": "tanker", "DC10": "tanker", "KC10": "tanker",
    "A332": "tanker_mrtt", "A310": "tanker_mrtt", "IL78": "tanker", "KC13": "tanker", "C30J_K": "tanker",
    # awacs / airborne C2
    "E3TF": "awacs", "E3CF": "awacs", "E3": "awacs", "E7": "awacs", "E737": "awacs", "A50": "awacs", "KJ50": "awacs",
    "E2": "awacs", "E2C": "awacs", "E2D": "awacs", "E6": "c2", "E4": "c2",
    # isr
    "RC135": "isr", "R135": "isr", "P8": "isr", "P3": "isr", "P3C": "isr", "Q4": "isr", "RQ4": "isr", "HAWK": "isr",
    "MQ9": "isr", "MQ4": "isr", "U2": "isr", "E8": "isr", "GLF5": "isr_biz", "G550": "isr_biz", "CL60": "isr_biz",
    "B350": "isr", "BE20": "isr", "PC12": "isr", "DHC6": "isr", "C560": "isr", "TEX2": "trainer", "EP3": "isr",
    "IL20": "isr", "IL38": "isr", "TU14": "isr", "Y8": "isr", "Y9": "isr", "R1": "isr", "CE68": "isr",
    # fighters
    "F16": "fighter", "F15": "fighter", "F18": "fighter", "F18S": "fighter", "FA18": "fighter", "F22": "fighter",
    "F35": "fighter", "EUFI": "fighter", "TYPH": "fighter", "RFAL": "fighter", "TORD": "fighter", "JAS39": "fighter",
    "GRIP": "fighter", "M2000": "fighter", "MIR2": "fighter", "SU27": "fighter", "SU30": "fighter", "SU35": "fighter",
    "SU57": "fighter", "MG29": "fighter", "MG31": "fighter", "J10": "fighter", "J11": "fighter", "J16": "fighter",
    "J20": "fighter", "F2": "fighter", "F4": "fighter", "F5": "fighter", "A10": "fighter", "SU25": "fighter",
    "HAR": "fighter", "AV8B": "fighter", "T50": "fighter", "KF21": "fighter", "TEJA": "fighter", "F14": "fighter",
    # bombers
    "B1": "bomber", "B2": "bomber", "B52": "bomber", "SU24": "bomber", "SU34": "bomber", "TU95": "bomber",
    "TU16": "bomber", "TU22": "bomber", "H6": "bomber", "JH7": "bomber",
    # transport
    "C17": "transport", "C5M": "transport", "C5": "transport", "C130": "transport", "C30J": "transport", "H130": "transport",
    "A400": "transport", "C27J": "transport", "C295": "transport", "CN35": "transport", "IL76": "transport",
    "AN12": "transport", "AN26": "transport", "AN72": "transport", "AN124": "transport", "A124": "transport",
    "Y20": "transport", "C2": "transport", "C1": "transport", "KC39": "transport", "C160": "transport", "C12": "transport",
    "C40": "transport", "B737": "transport", "B752": "transport", "C32": "transport", "A319": "transport",
    "A321": "transport", "A330": "transport", "B744": "transport", "C37": "vip", "GLF4": "vip", "GL5T": "vip", "VC25": "vip",
    "C21": "transport", "LJ35": "transport", "F900": "vip", "FA7X": "vip", "FA50": "vip", "E35L": "vip", "E55P": "vip",
    "DH8": "transport", "DHC8": "transport", "SB20": "transport", "ATR": "transport", "C146": "transport", "DO28": "transport",
    "CL60_T": "transport",
    # helicopters
    "H60": "helicopter", "UH60": "helicopter", "S70": "helicopter", "H64": "helicopter", "AH64": "helicopter",
    "H47": "helicopter", "CH47": "helicopter", "V22": "helicopter", "NH90": "helicopter", "EC35": "helicopter",
    "EC45": "helicopter", "H135": "helicopter", "H145": "helicopter", "EH10": "helicopter", "A139": "helicopter",
    "A109": "helicopter", "AS32": "helicopter", "AS50": "helicopter", "AS65": "helicopter", "H1": "helicopter",
    "UH1": "helicopter", "B412": "helicopter", "B429": "helicopter", "B06": "helicopter", "LYNX": "helicopter",
    "WLDC": "helicopter", "PUMA": "helicopter", "MI8": "helicopter", "MI17": "helicopter", "MI24": "helicopter",
    "MI28": "helicopter", "KA52": "helicopter", "S92": "helicopter", "H53": "helicopter", "MH60": "helicopter",
    "H225": "helicopter", "R44": "helicopter", "TIGR": "helicopter", "EC65": "helicopter",
    # trainers
    "T6": "trainer", "T38": "trainer", "PC21": "trainer", "PC9": "trainer", "PC7": "trainer", "HAWK_T": "trainer",
    "M346": "trainer", "T7": "trainer", "T45": "trainer", "TUCA": "trainer", "PC12_T": "trainer", "G120": "trainer",
    "SF26": "trainer", "T1": "trainer", "T44": "trainer", "L39": "trainer", "AJET": "trainer", "M339": "trainer",
}

# Il codice 'CL60' e' ambiguo (bizjet VIP o Artemis/ISR). Lo lasciamo isr_biz: conta come sorveglianza opportunista.
CALLSIGN_ROLE = [
    ("RCH", "transport"), ("REACH", "transport"), ("MOOSE", "transport"), ("HERK", "transport"), ("HERC", "transport"),
    ("ASCOT", "transport"), ("RRR", "transport"), ("GAF", "transport"), ("IAM", "transport"), ("FAF", "transport"),
    ("CTM", "transport"), ("PLF", "transport"), ("BAF", "transport"), ("NAF", "transport"), ("SVF", "transport"),
    ("ATLAS", "transport"), ("CFC", "transport"), ("RAAF", "transport"), ("IFC", "transport"), ("THK", "transport"),
    ("FORTE", "isr"), ("HOMER", "isr"), ("TOPCAT", "isr"), ("TRIDENT", "isr"), ("JAKE", "isr"), ("TEAL", "isr"),
    ("REDEYE", "isr"), ("NOBLE", "isr"), ("SPAR", "vip"), ("SAM", "vip"), ("EXEC", "vip"), ("VENUS", "vip"),
    ("SNTRY", "awacs"), ("NATO", "awacs"), ("MAGIC", "awacs"), ("DARKSTAR", "awacs"), ("BANDBOX", "awacs"),
    ("NCHO", "tanker"), ("PACK", "tanker"), ("SHELL", "tanker"), ("ETHYL", "tanker"), ("QUID", "tanker"),
    ("TARTN", "tanker"), ("SCOT", "tanker"), ("MMF", "tanker"), ("BLUE", "tanker"), ("GOLD", "tanker"), ("LAGR", "tanker"),
    ("DUKE", "fighter"), ("VIPER", "fighter"), ("EAGLE", "fighter"), ("RAPTOR", "fighter"), ("BOLT", "fighter"),
    ("HAVOC", "fighter"), ("COBRA", "fighter"), ("STEEL", "fighter"), ("MAKO", "fighter"), ("TIGER", "fighter"),
    ("BONE", "bomber"), ("DEATH", "bomber"), ("DOOM", "bomber"), ("MYTEE", "bomber"), ("BUFF", "bomber"),
    ("PEDRO", "helicopter"), ("JOLLY", "helicopter"), ("KING", "helicopter"),
]

HEX_NATION = [
    (0xADF7C8, 0xAFFFFF, "USA"), (0x43C000, 0x43CFFF, "UK"), (0x3B0000, 0x3B7FFF, "FRA"), (0x3F0000, 0x3F7FFF, "DEU"),
    (0x300000, 0x33FFFF, "ITA"), (0x140000, 0x15FFFF, "RUS"), (0x780000, 0x7BFFFF, "CHN"), (0x738000, 0x738FFF, "ISR"),
    (0x738000, 0x73FFFF, "NATO"), (0x4B8000, 0x4BFFFF, "TUR"), (0x340000, 0x37FFFF, "ESP"), (0x480000, 0x487FFF, "NLD"),
    (0x448000, 0x44FFFF, "BEL"), (0x468000, 0x46FFFF, "GRC"), (0x488000, 0x48FFFF, "POL"), (0x4A0000, 0x4A7FFF, "SWE"),
    (0x478000, 0x47FFFF, "NOR"), (0x458000, 0x45FFFF, "DNK"), (0xC00000, 0xC3FFFF, "CAN"), (0x7C0000, 0x7FFFFF, "AUS"),
    (0x840000, 0x87FFFF, "JPN"), (0x718000, 0x71FFFF, "KOR"), (0x800000, 0x83FFFF, "IND"), (0x710000, 0x717FFF, "SAU"),
    (0x896000, 0x896FFF, "ARE"), (0x010000, 0x017FFF, "EGY"), (0x760000, 0x767FFF, "PAK"), (0x730000, 0x737FFF, "IRN"),
    (0x768000, 0x76FFFF, "SGP"), (0x8A0000, 0x8A7FFF, "IDN"), (0xE40000, 0xE7FFFF, "BRA"), (0x498000, 0x49FFFF, "CZE"),
    (0x4A8000, 0x4AFFFF, "ROU"), (0x460000, 0x467FFF, "FIN"), (0x490000, 0x497FFF, "PRT"), (0x4B0000, 0x4B7FFF, "HUN"),
    (0x899000, 0x899FFF, "TWN"), (0x508000, 0x50FFFF, "UKR"), (0x720000, 0x727FFF, "PRK"), (0x4C0000, 0x4C7FFF, "IRL"),
    (0x4B0000, 0x4B0FFF, "CHE"), (0x440000, 0x447FFF, "AUT"), (0x700000, 0x700FFF, "AFG"), (0x706000, 0x706FFF, "IRQ"),
    (0x70C000, 0x70CFFF, "KWT"), (0x74C000, 0x74CFFF, "QAT"), (0x0D0000, 0x0D7FFF, "MAR"), (0x0A0000, 0x0A7FFF, "DZA"),
    (0x0C8000, 0x0C8FFF, "LBY"), (0x008000, 0x00FFFF, "ZAF"), (0x040000, 0x047FFF, "ETH"), (0x074000, 0x074FFF, "KEN"),
]

AWACS_ROLES = {"awacs", "c2"}
ISR_ROLES = {"isr", "isr_biz"}
TANKER_ROLES = {"tanker", "tanker_mrtt"}


def role_of(type_code, callsign):
    t = (type_code or "").strip().upper()
    if t in ROLE_BY_TYPE:
        return ROLE_BY_TYPE[t]
    for k, v in ROLE_BY_TYPE.items():
        if len(k) >= 3 and t.startswith(k):
            return v
    cs = (callsign or "").strip().upper()
    for p, r in CALLSIGN_ROLE:
        if cs.startswith(p):
            return r
    return "unknown"


def nation_of(hexcode):
    try:
        h = int(hexcode, 16)
    except (TypeError, ValueError):
        return "UNK"
    for lo, hi, n in HEX_NATION:
        if lo <= h <= hi:
            return n
    return "UNK"


def bucket(role):
    """Raggruppa nei 7 bucket usati dagli indicatori."""
    if role in TANKER_ROLES:
        return "tanker"
    if role in AWACS_ROLES:
        return "awacs"
    if role in ISR_ROLES:
        return "isr"
    if role in ("fighter", "bomber", "transport", "helicopter"):
        return role
    return "other"
