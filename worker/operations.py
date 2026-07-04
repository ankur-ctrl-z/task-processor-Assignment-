"""Pure text-processing operations the worker supports.

Kept side-effect free and easy to unit test in isolation from Mongo/Redis.
"""


def uppercase(text: str) -> str:
    return text.upper()


def lowercase(text: str) -> str:
    return text.lower()


def reverse_string(text: str) -> str:
    return text[::-1]


def word_count(text: str) -> str:
    return str(len(text.split()))


OPERATIONS = {
    "UPPERCASE": uppercase,
    "LOWERCASE": lowercase,
    "REVERSE_STRING": reverse_string,
    "WORD_COUNT": word_count,
}


def run_operation(operation: str, text: str) -> str:
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")
    return OPERATIONS[operation](text)
