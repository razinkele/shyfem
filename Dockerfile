
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
	openmpi-bin \
	libopenmpi-dev \
	libmetis-dev \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /root/shyfem-src

COPY . .

# build model (NODE-MPI default; METIS partitioning)
RUN make clean && make fem PARTS=METIS METISDIR=/usr

# Stage 2: Runtime (no build tools)
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
	libgfortran5 \
	libxt6 \
	libx11-6 \
	make \
	openmpi-bin \
	libopenmpi3 \
	libmetis5 \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/shyfem-src /root/shyfem-src

WORKDIR /root/shyfem-src

ENV PATH="/root/shyfem-src/bin:${PATH}"

CMD ["/bin/bash", "-c", "cd testcases/examples/mar_menor && make init && shyfem mm_hyd_00.str"]

