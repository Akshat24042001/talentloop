"""Copy TalentLoop's files (resumes, photos, recordings, interview records) from one S3 bucket to another, for
example from Supabase Storage in the old project to the new one.

Set the source and target as environment variables (the same names the app uses, with OLD_ and NEW_ in front):

    OLD_S3_ENDPOINT_URL  OLD_S3_REGION  OLD_S3_ACCESS_KEY_ID  OLD_S3_SECRET_ACCESS_KEY  OLD_S3_BUCKET
    NEW_S3_ENDPOINT_URL  NEW_S3_REGION  NEW_S3_ACCESS_KEY_ID  NEW_S3_SECRET_ACCESS_KEY  NEW_S3_BUCKET
    S3_PREFIX (optional, default "talentloop": the folder the app keeps its files in)

    python scripts/move_storage.py

Read-only on the source. A file already in the target with the same size is skipped, so it can be re-run safely.
Prints how many files and bytes are on each side at the end; they must match.
"""
import os
import sys


def client(p: str):
    import boto3
    from botocore.config import Config
    endpoint = (os.getenv(p + "S3_ENDPOINT_URL") or "").strip() or None
    path_style = os.getenv(p + "S3_PATH_STYLE", "") == "1" or bool(endpoint and ".supabase." in endpoint)
    return boto3.client("s3", endpoint_url=endpoint, region_name=(os.getenv(p + "S3_REGION") or "").strip() or "us-east-1",
                        aws_access_key_id=os.getenv(p + "S3_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv(p + "S3_SECRET_ACCESS_KEY"),
                        config=Config(retries={"max_attempts": 5, "mode": "standard"}, signature_version="s3v4",
                                      s3={"addressing_style": "path"} if path_style else None))


def listing(cli, bucket: str, prefix: str) -> dict[str, int]:
    out, token = {}, None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        r = cli.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            out[o["Key"]] = o["Size"]
        if not r.get("IsTruncated"):
            return out
        token = r["NextContinuationToken"]


def main() -> None:
    need = [p + k for p in ("OLD_", "NEW_") for k in ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET")]
    missing = [k for k in need if not os.getenv(k)]
    if missing:
        sys.exit("Missing: " + ", ".join(missing) + "\n\n" + __doc__)
    prefix = os.getenv("S3_PREFIX", "talentloop").strip().strip("/")
    prefix = prefix + "/" if prefix else ""
    old, new = client("OLD_"), client("NEW_")
    ob, nb = os.environ["OLD_S3_BUCKET"], os.environ["NEW_S3_BUCKET"]
    src, dst = listing(old, ob, prefix), listing(new, nb, prefix)
    print(f"{len(src)} files in the source ({sum(src.values()) / 1e6:.1f} MB), {len(dst)} already in the target.")
    copied = 0
    for key, size in src.items():
        if dst.get(key) == size:
            continue
        body = old.get_object(Bucket=ob, Key=key)["Body"].read()
        new.put_object(Bucket=nb, Key=key, Body=body)
        copied += 1
        if copied % 50 == 0:
            print(f"  {copied} copied...")
    dst = listing(new, nb, prefix)
    missing = [k for k, n in src.items() if dst.get(k) != n]
    print(f"Copied {copied}. Source: {len(src)} files, {sum(src.values())} bytes. Target: {len([k for k in dst if k in src])} of them, "
          f"{sum(dst[k] for k in src if k in dst)} bytes.")
    if missing:
        sys.exit(f"{len(missing)} file(s) did not copy, for example {missing[0]}. Run it again before switching S3_* on Render.")
    print("All files copied.")


if __name__ == "__main__":
    main()
