def parse_letters(raw: str, *, keep_yo: bool) -> frozenset[str]:
    """Собрать набор первых букв из строки вида «А,К,М» или «АКМ»."""
    letters: set[str] = set()
    for char in raw:
        if char.isspace() or char in ",;":
            continue
        if not char.isalpha():
            continue
        letters.add(_normalize(char, keep_yo=keep_yo))
    return frozenset(letters)


def surname_matches(last_name: str, letters: frozenset[str], *, keep_yo: bool) -> bool:
    letter = first_letter(last_name, keep_yo=keep_yo)
    return letter in letters


def first_letter(last_name: str, *, keep_yo: bool) -> str:
    name = last_name.strip()
    if not name:
        return ""
    return _normalize(name[0], keep_yo=keep_yo)


def _normalize(char: str, *, keep_yo: bool) -> str:
    folded = char.casefold()
    if keep_yo:
        return folded
    return folded.replace("ё", "е")
