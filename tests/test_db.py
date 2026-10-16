from app import db


def test_vector_extension_exists():
    db.init_db()
    assert db.vector_extension_version() is not None


def test_vector_type_works():
    with db.connect() as conn:
        distance = conn.execute("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector").fetchone()[0]
    assert distance == 1.0
