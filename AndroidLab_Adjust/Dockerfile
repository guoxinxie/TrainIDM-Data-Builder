# 基础镜像
FROM m.daocloud.io/docker.io/library/python:3.11-bullseye

# 换 apt 源
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list

# pip 换源 + flask
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install flask

# 安装依赖（❗去掉 default-jdk）
RUN apt-get update && apt-get install -y \
    vim \
    wget \
    unzip \
    libpulse-dev \
    libnss3 \
    cpu-checker \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxtst6 \
    libglib2.0-0 \
    libgl1 \
    libegl1 \
    libdbus-1-3 \
    libfontconfig1

# ===== 安装 OpenLogic Java 8 =====
COPY openlogic-openjdk-8u412-b08-linux-x64-deb.deb .
RUN apt install -y ./openlogic-openjdk-8u412-b08-linux-x64-deb.deb

# ✅ 关键：使用正确路径（方案二）
ENV JAVA_HOME=/usr/lib/jvm/openlogic-openjdk-8u412-b08
ENV PATH=$JAVA_HOME/bin:$PATH

# ===== Android SDK =====
ENV ANDROID_HOME=/root/.android
RUN mkdir -p $ANDROID_HOME

# 解压 SDK tools
COPY sdk-tools-linux-4333796.zip .
RUN unzip sdk-tools-linux-4333796.zip -d $ANDROID_HOME

# 写环境变量
RUN echo "export ANDROID_HOME=$ANDROID_HOME" >> /root/.bashrc \
 && echo 'export ANDROID_SDK_ROOT=$ANDROID_HOME' >> /root/.bashrc \
 && echo 'export PATH=$ANDROID_HOME/emulator:$ANDROID_HOME/tools:$ANDROID_HOME/tools/bin:$ANDROID_HOME/platform-tools:$PATH' >> /root/.bashrc

# ===== 安装 SDK（关键：显式指定 Java8 + 完整 PATH）=====
RUN /bin/bash -c "\
JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java)))) && \
export PATH=$JAVA_HOME/bin:$ANDROID_HOME/tools/bin:$ANDROID_HOME/platform-tools:$PATH && \
yes | $ANDROID_HOME/tools/bin/sdkmanager 'platform-tools' 'emulator'"

RUN /bin/bash -c "\
JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java)))) && \
export PATH=$JAVA_HOME/bin:$ANDROID_HOME/tools/bin:$ANDROID_HOME/platform-tools:$PATH && \
yes | $ANDROID_HOME/tools/bin/sdkmanager 'build-tools;33.0.0'"

RUN /bin/bash -c "\
JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java)))) && \
export PATH=$JAVA_HOME/bin:$ANDROID_HOME/tools/bin:$ANDROID_HOME/platform-tools:$PATH && \
yes | $ANDROID_HOME/tools/bin/sdkmanager 'platforms;android-33'"


# ===== 你的资源 =====
COPY skins.zip .
RUN unzip skins.zip -d /root/.android/

COPY Pixel_7_Pro_API_33.ini /root/.android/avd/
COPY Pixel_7_Pro_API_33.avd.zip .
RUN unzip Pixel_7_Pro_API_33.avd.zip -d /root/.android/avd/

COPY adb_client.py /

# system image
COPY x86_64.zip .
RUN mkdir -p /root/.android/system-images/android-33/google_apis/
RUN unzip x86_64.zip -d /root/.android/system-images/android-33/google_apis/

# ===== 清理 =====
RUN rm -rf \
    Pixel_7_Pro_API_33.avd.zip \
    openlogic-openjdk-8u412-b08-linux-x64-deb.deb \
    sdk-tools-linux-4333796.zip \
    skins.zip \
    x86_64.zip
