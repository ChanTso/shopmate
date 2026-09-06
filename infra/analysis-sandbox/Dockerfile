FROM python:3.11.13-slim-bookworm
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
COPY requirements.txt /opt/analysis/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r /opt/analysis/requirements.txt
COPY runner.py /opt/analysis/runner.py
USER 65532:65532
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "-B", "-u", "/opt/analysis/runner.py"]
