#!/bin/bash
set -eux
mkdir -p test_workspace
cd test_workspace

yes | rm -R remote_repo.git || true
git init --bare remote_repo.git

yes | rm -R test_repo || true
mkdir -p test_repo
cd test_repo
git init
dd if=/dev/random of=large_file.bin bs=1024 count=$((1024**2))
git lfs track large_file.bin
git config -f .lfsconfig lfs.url "http://localhost:8000"
git add .gitattributes .lfsconfig large_file.bin
git commit -m "initial commit"
git remote add remote_repo $(pwd)/../remote_repo.git
git push remote_repo main
cd ..

yes | rm -R cloned_test_repo || true
git clone remote_repo.git cloned_test_repo
