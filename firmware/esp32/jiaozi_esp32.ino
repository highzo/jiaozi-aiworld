/*
 * 饺子AIWorld · ESP32 家电节点固件
 * ---------------------------------------------------------------
 * 板子只做三件事：
 *   1. 每秒往局域网喊一声「我是谁、我有几路开关」（UDP 组播 + 广播）
 *   2. 提供一个很小的 HTTP 接口：/api/info、/api/state、/api/cmd
 *   3. 听到电脑喊 esp.find 就单独回一条
 *
 * 没有长连接、没有重连逻辑、没有心跳超时 —— 断电再插上，三秒后自己回来。
 *
 * 烧写：Arduino IDE 选 ESP32 Dev Module，把下面 4 个地方改成你自己的，
 *       然后上传。串口会打印拿到的 IP。
 * 接线：继电器模块 VCC→5V(或3.3V，看模块) GND→GND IN→下面的 PIN。
 *       强电那边请务必断电作业，不确定就别碰，用成品智能插座改。
 *
 * 只用 ESP32 core 自带的库，不需要在库管理器里装任何东西。
 */

#include <WiFi.h>
#include <WebServer.h>
#include <WiFiUdp.h>

// ================= 改这里 =================
const char* WIFI_SSID    = "你的WiFi名字";
const char* WIFI_PASS    = "你的WiFi密码";

const char* DEV_ID       = "esp32-jiaozi01";  // 全屋唯一，改一次以后别动
const char* DEV_NAME     = "客厅灯";           // 电脑上显示的名字
const char* JZ_KEY       = "";                // 访问密钥，留空=不校验（同一 WiFi 内）
// ==========================================

const uint16_t HTTP_PORT      = 80;
const uint16_t DISCOVERY_PORT = 8789;
const uint32_t ANNOUNCE_MS    = 1000;

IPAddress MULTICAST(239, 255, 77, 88);
WiFiUDP udp;
WebServer server(HTTP_PORT);

/* 每一路开关。active_low=true 对应「低电平触发」的继电器模块（大多数蓝色模块都是）。 */
struct Channel {
  const char* id;
  const char* name;
  const char* type;
  uint8_t pin;
  bool active_low;
  bool on;
};

Channel CH[] = {
  { "r1", "灯",   "relay", 26, true,  false },
  { "r2", "风扇", "relay", 27, true,  false },
};
const int CH_N = sizeof(CH) / sizeof(CH[0]);

uint32_t bootMs = 0;
uint32_t lastAnnounce = 0;

/* ---------------------------------------------------------------- 工具 */

void applyPin(Channel& c) {
  digitalWrite(c.pin, c.active_low ? (c.on ? LOW : HIGH) : (c.on ? HIGH : LOW));
}

/* 从请求体里抠一个字符串字段。请求是我们自己的电脑发的，格式固定，
   所以不做完整 JSON 解析 —— 换来的是固件不用装任何库。 */
bool jsonStr(const String& body, const char* key, String& out) {
  String pat = String("\"") + key + "\"";
  int i = body.indexOf(pat);
  if (i < 0) return false;
  i = body.indexOf(':', i + pat.length());
  if (i < 0) return false;
  i = body.indexOf('"', i + 1);
  if (i < 0) return false;
  int j = body.indexOf('"', i + 1);
  if (j < 0) return false;
  out = body.substring(i + 1, j);
  return true;
}

bool jsonBool(const String& body, const char* key, bool& out) {
  String pat = String("\"") + key + "\"";
  int i = body.indexOf(pat);
  if (i < 0) return false;
  i = body.indexOf(':', i + pat.length());
  if (i < 0) return false;
  String rest = body.substring(i + 1);
  rest.trim();
  if (rest.startsWith("true"))  { out = true;  return true; }
  if (rest.startsWith("false")) { out = false; return true; }
  return false;  // 也可能是数字，交给调用方
}

String esc(const String& s) {
  String o;
  for (int i = 0; i < (int)s.length(); i++) {
    char c = s[i];
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if (c == '\n') o += ' ';
    else o += c;
  }
  return o;
}

/* ---------------------------------------------------------------- 输出 */

String channelsJson(bool withState) {
  String s = "{";
  for (int i = 0; i < CH_N; i++) {
    if (i) s += ",";
    s += "\"" + String(CH[i].id) + "\":{";
    s += "\"name\":\"" + esc(CH[i].name) + "\",";
    s += "\"type\":\"" + String(CH[i].type) + "\"";
    if (withState) s += String(",\"on\":") + (CH[i].on ? "true" : "false");
    s += "}";
  }
  return s + "}";
}

String infoJson() {
  String s = "{";
  s += "\"id\":\"" + String(DEV_ID) + "\",";
  s += "\"name\":\"" + esc(DEV_NAME) + "\",";
  s += "\"model\":\"esp32\",";
  s += "\"fw\":\"1.0\",";
  s += "\"proto\":1,";
  s += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  s += "\"port\":" + String(HTTP_PORT) + ",";
  s += "\"caps\":[\"relay\",\"sensor\"],";
  s += "\"channels\":[";
  for (int i = 0; i < CH_N; i++) {
    if (i) s += ",";
    s += "{\"id\":\"" + String(CH[i].id) + "\",";
    s += "\"name\":\"" + esc(CH[i].name) + "\",";
    s += "\"type\":\"" + String(CH[i].type) + "\"}";
  }
  s += "]}";
  return s;
}

String stateJson() {
  String s = "{\"ok\":true,\"data\":{";
  s += "\"channels\":" + channelsJson(true) + ",";
  s += "\"sensors\":{},";   // 以后接了 DHT22 之类，往这里塞 {"temp":24.5}
  s += "\"uptime\":" + String((millis() - bootMs) / 1000) + ",";
  s += "\"rssi\":" + String(WiFi.RSSI());
  s += "}}";
  return s;
}

/* ---------------------------------------------------------------- HTTP */

bool authed() {
  if (strlen(JZ_KEY) == 0) return true;
  return server.header("X-JZ-Key") == String(JZ_KEY);
}

void sendJson(int code, const String& body) {
  server.sendHeader("Cache-Control", "no-store");
  server.send(code, "application/json; charset=utf-8", body);
}

void handleInfo() {
  if (!authed()) { sendJson(401, "{\"ok\":false,\"error\":\"key\"}"); return; }
  sendJson(200, "{\"ok\":true,\"data\":" + infoJson() + "}");
}

void handleState() {
  if (!authed()) { sendJson(401, "{\"ok\":false,\"error\":\"key\"}"); return; }
  sendJson(200, stateJson());
}

void handleCmd() {
  if (!authed()) { sendJson(401, "{\"ok\":false,\"error\":\"key\"}"); return; }
  String body = server.arg("plain");
  String cid;
  if (!jsonStr(body, "channel", cid)) {
    sendJson(400, "{\"ok\":false,\"error\":\"need channel\"}");
    return;
  }
  Channel* hit = nullptr;
  for (int i = 0; i < CH_N; i++) if (cid == CH[i].id) hit = &CH[i];
  if (!hit) { sendJson(400, "{\"ok\":false,\"error\":\"unknown channel\"}"); return; }

  bool on = false, hasOn = jsonBool(body, "on", on);
  bool tg = false, hasTg = jsonBool(body, "toggle", tg);
  if (hasOn)      hit->on = on;
  else if (hasTg && tg) hit->on = !hit->on;
  else {
    sendJson(400, "{\"ok\":false,\"error\":\"need on or toggle\"}");
    return;
  }
  applyPin(*hit);
  Serial.printf("[cmd] %s -> %s\n", cid.c_str(), hit->on ? "ON" : "OFF");

  String s = "{\"ok\":true,\"data\":{\"channel\":\"" + cid + "\",\"on\":";
  s += hit->on ? "true" : "false";
  s += ",\"channels\":" + channelsJson(true) + "}}";
  sendJson(200, s);
}

/* ---------------------------------------------------------------- 喊话 */

void announce(const IPAddress* to) {
  String p = "{\"proto\":1,\"t\":\"esp.announce\",";
  p += "\"id\":\"" + String(DEV_ID) + "\",";
  p += "\"name\":\"" + esc(DEV_NAME) + "\",";
  p += "\"model\":\"esp32\",\"fw\":\"1.0\",";
  p += "\"port\":" + String(HTTP_PORT) + ",";
  p += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  p += "\"caps\":[\"relay\",\"sensor\"],";
  p += "\"channels\":[";
  for (int i = 0; i < CH_N; i++) {
    if (i) p += ",";
    p += "{\"id\":\"" + String(CH[i].id) + "\",\"name\":\"" + esc(CH[i].name) +
         "\",\"type\":\"" + String(CH[i].type) + "\"}";
  }
  p += "]}";

  if (to) {
    udp.beginPacket(*to, DISCOVERY_PORT);
  } else {
    udp.beginPacket(MULTICAST, DISCOVERY_PORT);
  }
  udp.write((const uint8_t*)p.c_str(), p.length());
  udp.endPacket();

  if (!to) {  // 顺便广播一份：有的路由器不放组播
    udp.beginPacket(IPAddress(255, 255, 255, 255), DISCOVERY_PORT);
    udp.write((const uint8_t*)p.c_str(), p.length());
    udp.endPacket();
  }
}

void pollDiscovery() {
  int n = udp.parsePacket();
  if (n <= 0) return;
  char buf[320];
  int len = udp.read(buf, sizeof(buf) - 1);
  if (len <= 0) return;
  buf[len] = 0;
  if (strstr(buf, "\"esp.find\"")) {
    IPAddress from = udp.remoteIP();
    announce(&from);  // 谁问的就单独回给谁
  }
}

/* ---------------------------------------------------------------- 主流程 */

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[饺子] 家电节点启动");

  for (int i = 0; i < CH_N; i++) {
    pinMode(CH[i].pin, OUTPUT);
    CH[i].on = false;
    applyPin(CH[i]);
  }

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEV_ID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[wifi] 连接中");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 30000) {
    delay(400);
    Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[wifi] 连不上。检查名字密码，或者路由器是不是开了 MAC 过滤。");
    Serial.println("[wifi] 20 秒后重启再试。");
    delay(20000);
    ESP.restart();
  }
  Serial.printf("\n[wifi] 已连上 %s  IP=%s\n",
                WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());

  server.on("/api/info",  HTTP_GET,  handleInfo);
  server.on("/api/state", HTTP_GET,  handleState);
  server.on("/api/cmd",   HTTP_POST, handleCmd);
  server.onNotFound([]() {
    sendJson(404, "{\"ok\":false,\"error\":\"not found\"}");
  });
  server.begin();

  udp.begin(DISCOVERY_PORT);
  udp.beginMulticast(MULTICAST, DISCOVERY_PORT);

  bootMs = millis();
  announce(nullptr);
  Serial.println("[net] 已在喊话，电脑上打开「家电」应该能看到我了");
}

void loop() {
  server.handleClient();
  pollDiscovery();

  if (millis() - lastAnnounce > ANNOUNCE_MS) {
    lastAnnounce = millis();
    announce(nullptr);
  }

  // WiFi 掉线就重连，别卡死在死循环里
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] 掉线，重连…");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    delay(500);
  }
}
