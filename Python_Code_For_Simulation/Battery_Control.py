import paho.mqtt.client as mqtt
import json


MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC = "microgrid/control/battery"

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[BESS Local Controller] เชื่อมต่อสำเร็จ! กำลังรอรับคำสั่งจาก Digital Twin...")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"เชื่อมต่อล้มเหลว Code: {rc}")

def on_message(client, userdata, msg):
    received_string = msg.payload.decode()
    data = json.loads(received_string)
    
    hour = data.get("hour", 0)
    cmd_mw = data.get("battery_cmd_mw", 0.0)
    soc = data.get("new_soc_percent", 0.0)

    print("\n" + "="*50)
    print(f" เวลาปัจจุบัน: {hour}:00 น.")
    print(f" ได้รับคำสั่งควบคุมจาก AI (Microgrid Controller)")
    
    if cmd_mw > 0:
        print(f" สถานะ Inverter : [ DISCHARGING ] จ่ายไฟช่วยระบบ {cmd_mw:.3f} MW")
    elif cmd_mw < 0:
        print(f" สถานะ Inverter : [ CHARGING ] ชาร์จไฟเก็บ {abs(cmd_mw):.3f} MW")
    else:
        print(f" สถานะ Inverter : [ IDLE ] สแตนด์บาย (0.000 MW)")
        
    print(f" ปริมาณแบตเตอรี่คงเหลือ (SOC): {soc:.1f}%")
    print("="*50)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "battery-emulator-script")
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, 1883)
client.loop_forever()