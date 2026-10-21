from fastapi import FastAPI
from fastapi.testclient import TestClient
from orca_ui.api.assembly import build_router


def client_for(path):
    app = FastAPI()
    app.include_router(build_router(path))
    return TestClient(app)


def test_progress_survives_new_server_and_browser(tmp_path):
    path = tmp_path / 'assembly.json'
    client = client_for(path)
    assert client.get('/api/assembly/progress').json() is None
    progress = dict(current='p83', done=['p6'], tendons=[0, 31], checks=['p139:0'],
                    views={'p83': './assembly/media/mapping-left-1.jpg'},
                    build=dict(side='left', motor='feetech', version='touch', audience='external'))
    assert client.put('/api/assembly/progress', json=progress).status_code == 200
    assert client_for(path).get('/api/assembly/progress').json() == progress
    assert len(list(tmp_path.iterdir())) == 1


def test_reject_invalid_progress_without_overwriting(tmp_path):
    path = tmp_path / 'assembly.json'
    client = client_for(path)
    client.put('/api/assembly/progress', json={'current': 'p26'})
    original = path.read_bytes()
    for data in [{'tendons': [32]}, {'build': {'side': 'unknown'}}, {'build': {'audience': 'unknown'}}, {'done': ['x'] * 201}]:
        assert client.put('/api/assembly/progress', json=data).status_code == 422
        assert path.read_bytes() == original


def test_corrupt_storage_reports_failure_without_erasing_it(tmp_path):
    path = tmp_path / 'assembly.json'
    path.write_text('not json')
    assert client_for(path).get('/api/assembly/progress').status_code == 503
    assert path.read_text() == 'not json'
