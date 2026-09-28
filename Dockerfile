FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    git cmake ninja-build clang \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone https://github.com/KryptIT/luraph-v15-v14.x-deobfuscator.git .

RUN git clone https://github.com/luau-lang/luau.git /luau && \
    cd /luau && mkdir build && cd build && \
    cmake ../ -G Ninja -DCMAKE_BUILD_TYPE=Release && \
    ninja luau luau-compile luau-analyze

RUN cp /luau/build/luau /app/Deobfuscator/deobf/bin/luau && \
    cp /luau/build/luau-compile /app/Deobfuscator/deobf/bin/luau-compile && \
    cp /luau/build/luau-analyze /app/Deobfuscator/deobf/bin/luau-analyze && \
    chmod +x /app/Deobfuscator/deobf/bin/luau*

RUN sed -i 's/luau\.exe/luau/g' /app/Deobfuscator/deobf/harness.py && \
    sed -i 's/luau-compile\.exe/luau-compile/g' /app/Deobfuscator/deobf/harness.py && \
    sed -i 's/luau-analyze\.exe/luau-analyze/g' /app/Deobfuscator/deobf/harness.py

RUN pip install flask

COPY main.py .

CMD ["python", "main.py"]
