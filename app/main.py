from fastapi import FastAPI

app = FastAPI(title="aobp")


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Hello, world!"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
