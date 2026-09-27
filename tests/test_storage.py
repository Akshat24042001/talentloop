"""S3 persistence: survive a host that wipes its disk (Render free). No network: python -m tests.test_storage"""
import importlib
import os
import shutil
import tempfile
from pathlib import Path


def main():
    from moto import mock_aws

    data = Path(tempfile.mkdtemp())
    os.environ.update({"DATA_DIR": str(data), "S3_BUCKET": "tl-test", "S3_ACCESS_KEY_ID": "x", "S3_SECRET_ACCESS_KEY": "y",
                       "S3_REGION": "us-east-1", "S3_PREFIX": "talentloop", "AWS_DEFAULT_REGION": "us-east-1"})
    os.environ.pop("S3_ENDPOINT_URL", None)
    with mock_aws():
        from backend import store
        store = importlib.reload(store)
        assert store.S3_ENABLED
        store.s3().create_bucket(Bucket="tl-test")

        rec = {"id": "abcDEF123", "status": "scored", "plan": {"questions": []}, "created_at": 1}
        store.save(rec)
        (store.MEDIA_DIR / rec["id"]).mkdir(parents=True, exist_ok=True)
        (store.MEDIA_DIR / rec["id"] / "camera_x1.webm").write_bytes(b"VIDEO" * 1000)
        store.upload_media(rec["id"], "camera_x1.webm")
        store.flush()
        keys = sorted(o["Key"] for o in store.s3().list_objects_v2(Bucket="tl-test")["Contents"])
        print("in bucket:", keys)
        assert keys == ["talentloop/interviews/abcDEF123.json", "talentloop/media/abcDEF123/camera_x1.webm"]

        # simulate a restart on a fresh disk
        shutil.rmtree(data)
        data.mkdir()
        store = importlib.reload(store)
        assert store.load("abcDEF123")["status"] == "scored", "load() must fall back to S3"
        (store.INT_DIR / "abcDEF123.json").unlink()
        assert store.restore_all() == 1 and store.list_all()[0]["id"] == "abcDEF123"
        p = store.media_path("abcDEF123", "camera_x1.webm")
        assert p and p.read_bytes() == b"VIDEO" * 1000, "media must come back from S3"

        # path tricks never reach S3 or disk
        for bad in ("../x", "a/b", ".hidden", ""):
            try:
                store.media_path("abcDEF123", bad)
                raise AssertionError(f"accepted bad name {bad!r}")
            except ValueError:
                pass
        assert store.media_path("../etc", "x.webm") is None

        store.delete("abcDEF123")
        assert "Contents" not in store.s3().list_objects_v2(Bucket="tl-test"), "delete must remove S3 copies"
        assert store.load("abcDEF123") is None
    for k in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        os.environ.pop(k, None)
    print("STORAGE CHECKS PASSED")


if __name__ == "__main__":
    main()
