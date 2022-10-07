FROM alpine:3.16
VOLUME /var/startup
COPY requirements.txt regilo.py
RUN \
	apk add --no-cache python3 py3-pip && \
	pip3 install -r /requirements.txt && \
	apk del py3-pip && \
	rm -f /requirements.txt
ENTRYPOINT ["/regilo.py"]
