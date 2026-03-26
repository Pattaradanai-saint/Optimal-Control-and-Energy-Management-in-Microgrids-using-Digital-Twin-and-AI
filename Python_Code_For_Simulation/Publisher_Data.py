import time
import json
import schedule
import paho.mqtt.client as mqtt
from datetime import date, timedelta

# =============================================================================
# 1. CONFIGURATION & DATA PROFILES
# =============================================================================
MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC = "loaddata"

# PV Generation Profiles (kW)
PV1 = [ # ฤดูหนาว (ต.ค. - ม.ค.)
    0, 0, 0, 0, 0, 0, 0,
    253.38675, 872.6755, 1395.64475, 1765.58775, 2019.83575, 2075.62725,
    1979.26375, 1710.24, 1280.082, 700.905, 159.61575, 0,
    0, 0, 0, 0, 0
] 

PV2 = [ # ฤดูร้อน (ก.พ. - พ.ค.)
    0, 0, 0, 0, 0, 0,
    5.87, 339.44225, 884.06125, 1388.136, 1742.85475, 1969.1,
    2067.7365, 2016.60225, 1800.59975, 1396.599, 896.4745, 329.52775,
    7.069, 0, 0, 0, 0, 0
] 

PV3 = [ # ฤดูฝน (มิ.ย. - ก.ย.)
    0, 0, 0, 0, 0, 0,
    27.55275, 250.4305, 592.3685, 971.30475, 1244.9365, 1426.951,
    1562.5555, 1563.58525, 1452.1475, 1188.86125, 814.32375, 376.27425,
    33.881, 0, 0, 0, 0, 0
] 

# Active Power (MW)
LOADDATAP = [
    0.3096, 0.2880, 0.2736, 0.2664, 0.2808, 0.3240,
    0.3960, 0.4104, 0.3600, 0.3456, 0.3384, 0.3672,
    0.3600, 0.3456, 0.4176, 0.4608, 0.4680, 0.3888,
    0.4752, 0.5112, 0.4896, 0.4536, 0.4032, 0.3528
] 

# Reactive Power (MVAR)
LOADDATAQ = [
    0.2322, 0.2160, 0.2052, 0.1998, 0.2106, 0.2430,
    0.2970, 0.3078, 0.2700, 0.2592, 0.2538, 0.2754,
    0.2700, 0.2592, 0.3132, 0.3456, 0.3510, 0.2916,
    0.3564, 0.3834, 0.3672, 0.3402, 0.3024, 0.2646
]

# =============================================================================
# 2. GLOBAL VARIABLES & INITIALIZATION
# =============================================================================
i = 0  
start_day = date(2025, 1, 1)
check_date = start_day

# =============================================================================
# 3. CORE FUNCTIONS
# =============================================================================
def send_data():
    global i, check_date
    current_index = i % len(LOADDATAP)
    
    # ตรวจสอบเดือนและวันเพื่อเลือก PV Profile (ฤดูกาล)
    m = check_date.month
    d = check_date.day
    md = (m, d)
    
    if md >= (10, 1) or md <= (1, 31):
        selected_pv = PV1[current_index]     # ฤดูหนาว
    elif (2, 1) <= md <= (5, 31):
        selected_pv = PV2[current_index]     # ฤดูร้อน
    else:
        selected_pv = PV3[current_index]     # ฤดูฝน
    
    # เตรียมแพ็กเกจข้อมูล
    data_to_send = {
        "load_P": LOADDATAP[current_index],
        "load_Q": LOADDATAQ[current_index],
        "pv_P":   selected_pv,
    }
    
    message = json.dumps(data_to_send)
    
    # นับรอบและส่งข้อมูล
    i = i + 1
    client.publish(MQTT_TOPIC, message)
    
    # คำนวณวันที่ใหม่ (1 วันมี 24 ชั่วโมง)
    check_date = start_day + timedelta(days=(i-1)//24)
    
    print(f"Published to time: {(i-1)%24:.2f} - {i%24:.2f} date: {check_date} {MQTT_TOPIC}: {message}")

# =============================================================================
# 4. MQTT SETUP & MAIN EXECUTION
# =============================================================================
if __name__ == "__main__":
    # ตั้งค่าและเชื่อมต่อ MQTT Client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "sender-script")
    client.connect(MQTT_BROKER, 1883)
    client.loop_start()

    # ตั้งเวลาส่งข้อมูลทุกๆ 1 วินาที (เร่งความเร็ว Simulation)
    schedule.every(1).seconds.do(send_data)

    print("Publisher is running...")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping publisher...")
        client.loop_stop()
        client.disconnect()
        print("Disconnected successfully.")