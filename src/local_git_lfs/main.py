import aiofiles
import argparse
from datetime import datetime
from enum import Enum
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.wsgi import WSGIMiddleware
from flask import Flask
import hashlib
import os
from pathlib import Path
from pydantic import BaseModel
import shutil
from typing import Dict, List, Union
import uuid
import uvicorn


parser = argparse.ArgumentParser()
parser.add_argument("--host", type=str, default="0.0.0.0")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--git-object-dir", type=str, default="tmp")
parser.add_argument("--max-git-object-size", type=int, default=20*(1024**3))  # default is 20GB
args = parser.parse_args()


app = FastAPI()


GIT_OBJECT_DIR = Path(args.git_object_dir)
MAX_GIT_OBJECT_SIZE = args.max_git_object_size


class OperationEnum(str, Enum):
    upload = "upload"
    download = "download"


class GitObjectRequestInfo(BaseModel):
    oid: str
    size: int


class BatchRequest(BaseModel):
    operation: OperationEnum
    transfers: List[str] = ["basic"]
    objects: List[GitObjectRequestInfo]
    hash_algo: str = "sha256"


class DownloadAction(BaseModel):
    href: str
    # header
    # expires_at


class UploadAction(BaseModel):
    href: str
    # header
    # expires_at


class GitObjectResponseInfo(BaseModel):
    oid: str
    size: int
    actions: Dict[str, Union[DownloadAction, UploadAction]]


class GitObjectErrorResponseInfo(BaseModel):
    oid: str
    size: int
    error: Dict[str, Union[int, str]]


class BatchResponse(BaseModel):
    transfer: str = "basic"
    objects: List[GitObjectResponseInfo]
    hash_algo: str = "sha256"


@app.post("/objects/batch")
async def batch(request: BatchRequest, raw_request: Request):
    if request.hash_algo != "sha256":
        raise ValueError(f"{request.hash_algo} is not supported")

    base_url = f"{raw_request.url.scheme}://{raw_request.url.hostname}:{raw_request.url.port}"

    response = BatchResponse(objects=[])
    for git_object in request.objects:
        if git_object.size > MAX_GIT_OBJECT_SIZE:
            raise HTTPException(status_code=422)  # Unprocessable entity

        if request.operation == OperationEnum.upload:
            action = UploadAction(href=f"{base_url}/objects/{git_object.oid}")
        elif request.operation == OperationEnum.download:
            if not git_object_exists(oid=git_object.oid):
                response.objects.apppend(
                    GitObjectErrorResponseInfo(
                        oid=git_object.oid,
                        size=git_object.size,
                        error=dict(code=404, message="git object not found"),
                    ),
                )
                continue
            action = DownloadAction(href=f"{base_url}/objects/{git_object.oid}")
        else:
            raise NotImplementedError()
        response_obj = GitObjectResponseInfo(
            oid=git_object.oid,
            size=git_object.size,
            actions={request.operation.value: action},
        )
        response.objects.append(response_obj)

    print(response)
    return response


@app.put("/objects/{oid}")
async def upload_object(oid: str, request: Request):
    print("upload")
    if git_object_exists(oid=oid):
        print("already exist. uploading is not executed")
    else:
        m = hashlib.sha256()
        unique_string = f"{uuid.uuid4().hex}_{int(datetime.now().timestamp())}"
        temp_object_file_path = GIT_OBJECT_DIR / f"{oid}.{unique_string}"
        file_size = 0
        async with aiofiles.open(temp_object_file_path, "wb") as out_file:
            async for chunk in request.stream():
                file_size += len(chunk)
                if file_size > MAX_GIT_OBJECT_SIZE:
                    raise HTTPException(status_code=400, detail="file size is too large")
                m.update(chunk)
                await out_file.write(chunk)
        if m.hexdigest() != oid:
            temp_object_file_path.unlink()
            raise HTTPException(status_code=400, detail="hash does not match")
        os.replace(temp_object_file_path, GIT_OBJECT_DIR / oid)  # os.replace() is atomic operation


@app.get("/objects/{oid}")
async def download_object(oid: str):
    print("download")
    if not git_object_exists(oid=oid):
        raise HTTPException(status_code=404, detail="git object is not found")

    def iterfile():
        with open(GIT_OBJECT_DIR / oid, mode="rb") as f:
            yield from f
    return StreamingResponse(iterfile(), media_type="application/octet-stream")


def git_object_exists(oid: str) -> bool:
    return (GIT_OBJECT_DIR / oid).exists()


def remove_git_object(oid: str) -> None:
    shutil.rmtree(GIT_OBJECT_DIR / oid)


# flask frontend
flask_app = Flask(__name__)
app.mount("/", WSGIMiddleware(flask_app))


@flask_app.route("/")
def index():
    return "hello"


def serve():
    uvicorn.run("local_git_lfs.main:app", host=args.host, port=args.port)
