FROM nonebot/nb-cli:latest
WORKDIR /
# 安装调试工具（curl 和 ping）
RUN apt-get update && apt-get install -y \
    curl \
    iputils-ping 

COPY . /MaiMBot/
WORKDIR /MaiMBot
RUN mkdir config
RUN mv env.example config/.env \
&& mv src/plugins/chat/bot_config_toml config/bot_config.toml
RUN ln -s /MaiMBot/config/.env /MaiMBot/.env  \
&& ln -s /MaiMBot/config/bot_config.toml /MaiMBot/src/plugins/chat/bot_config.toml
RUN pip install -r requirements.txt
VOLUME [ "/MaiMBot/config" ]
EXPOSE 8080
ENTRYPOINT [ "nb","run" ]