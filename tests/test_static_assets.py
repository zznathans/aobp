from fastapi.testclient import TestClient


def test_base_stylesheet_is_served(client: TestClient) -> None:
    response = client.get("/static/base.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".navbar" in response.text


def test_per_page_stylesheet_is_served(client: TestClient) -> None:
    response = client.get("/static/card.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".item-card" in response.text
