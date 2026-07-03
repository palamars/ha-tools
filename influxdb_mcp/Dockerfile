ARG BUILD_ARCH=amd64
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY run.sh /run.sh
COPY app /app/app

RUN chmod a+x /run.sh

CMD ["/run.sh"]
