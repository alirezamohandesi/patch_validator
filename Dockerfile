# One container per CI job.  Target executions get a lightweight bubblewrap
# sandbox *inside* this container; the validator never talks to a Docker
# daemon or socket (architecture amendment, ADR-002).
#
# Build:
#   docker build -t patch-validator .
#
# Run (verified on an Ubuntu 24.04 host, Docker 29):
#   cid=$(docker run -d \
#       --security-opt seccomp=unconfined \
#       --security-opt apparmor=unconfined \
#       --security-opt systempaths=unconfined \
#       --cap-add=SYS_ADMIN \
#       patch-validator validate --config /opt/src/configs/recparse.yaml)
#   docker wait "$cid"                       # the validator's exit code
#   docker cp "$cid:/project/runs" ./runs    # the artifacts
#   docker rm "$cid"
#
# Each flag answers one specific restriction, and `patch-validator doctor`
# names which one is missing rather than reporting a generic failure:
#
#   seccomp=unconfined      Docker's default seccomp profile blocks clone(2)
#                           flags that bubblewrap needs.
#   systempaths=unconfined  Docker masks paths under /proc, and the kernel
#                           refuses to mount a fresh procfs while the visible
#                           one has masked submounts. Without this, the
#                           sandbox fails with "Can't mount proc".
#   apparmor=unconfined     Required together on hosts where
#   + --cap-add=SYS_ADMIN   kernel.apparmor_restrict_unprivileged_userns=1
#                           (Ubuntu 24.04 and later): unprivileged user
#                           namespaces are permitted only for binaries
#                           covered by an AppArmor profile, which a copy of
#                           bubblewrap inside a container is not. Setting that
#                           sysctl to 0 on the host removes the need for
#                           SYS_ADMIN entirely.
#
# Run the container as root. Dropping to --user breaks the capability the
# sandbox needs, which is why artifacts are copied out rather than written to
# a bind mount.
#
# --privileged also works and is never required. If the sandbox cannot be
# created the tool exits 30 and writes a report explaining why, rather than
# running a known-vulnerable binary unprotected.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# bubblewrap        the sandbox backend
# util-linux        prlimit, used to bound process count inside the namespace
# binutils          readelf, the source of the hardening evidence
# gcc/cmake/make    building the targets under test
RUN apt-get update && apt-get install -y --no-install-recommends \
        bubblewrap \
        util-linux \
        binutils \
        build-essential \
        cmake \
        git \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# The virtual environment keeps the tool's dependencies off the system
# interpreter, which Ubuntu marks as externally managed.
ENV VIRTUAL_ENV=/opt/patch-validator
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /opt/src

# Dependencies first so editing source does not invalidate the layer.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY targets ./targets
COPY configs ./configs
COPY tests ./tests
COPY docs ./docs

# Materialise the toy target repository so the image is usable with no
# network and no extra setup.
RUN bash targets/recparse/bootstrap.sh

WORKDIR /project
ENTRYPOINT ["patch-validator"]
CMD ["doctor"]
