from app.core.response_parser import ResponseParser


def test_response_parser_valid_json():
    parser = ResponseParser()
    result = parser.parse('{"tool": "read_file", "args": {"path": "file.txt"}}')

    assert result["status"] == "success"
    assert result["data"]["tool"] == "read_file"
    assert result["data"]["args"]["path"] == "file.txt"


def test_response_parser_invalid_json():
    parser = ResponseParser()
    result = parser.parse("not valid json")

    assert result["status"] == "error"
    assert "raw" in result
