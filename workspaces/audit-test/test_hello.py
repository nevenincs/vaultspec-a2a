from hello import hello


def test_hello_returns_expected_string() -> None:
    assert hello() == "Hello, world!"
