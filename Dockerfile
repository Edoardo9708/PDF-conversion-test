FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make automake autoconf libtool pkg-config git ca-certificates \
    libleptonica-dev libopenjp2-tools libxml2-dev libxslt1-dev \
    libjpeg-dev libpng-dev zlib1g-dev \
    tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*
# Official MRC renderer uses jbig2enc for the losslessly encoded text mask.
RUN git clone --depth 1 https://github.com/agl/jbig2enc.git /tmp/jbig2enc \
    && cd /tmp/jbig2enc && ./autogen.sh && ./configure \
    && make -j2 && make install && ldconfig \
    && rm -rf /tmp/jbig2enc
RUN python -m pip install --upgrade pip \
    && python -m pip install archive-pdf-tools==1.5.7
WORKDIR /opt/pdf-optimizer
COPY backend.py server.py index.html ./
COPY tests/smoke.py tests/smoke.py
EXPOSE 8765
CMD ["python", "server.py"]
