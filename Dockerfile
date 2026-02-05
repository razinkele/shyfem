
#------------------------------------------------------------------------
#
#    Copyright (C) 1985-2020  Georg Umgiesser
#
#    This file is part of SHYFEM.
#
#------------------------------------------------------------------------

# Stage 1: Build
FROM debian:bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
	g++ \
	gfortran \
	libxt-dev \
	libx11-dev \
	make \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /root/shyfem-src

COPY . .

# install (soft-links current directory to /root/shyfem)
RUN make install

# build model
RUN make clean && make fem

# Stage 2: Runtime (no build tools)
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
	libgfortran5 \
	libxt6 \
	libx11-6 \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/shyfem-src /root/shyfem-src
COPY --from=builder /root/shyfem /root/shyfem

WORKDIR /root/shyfem-src

ENV PATH="/root/shyfem/bin:${PATH}"

CMD ./examples/mar_menor/run.sh

