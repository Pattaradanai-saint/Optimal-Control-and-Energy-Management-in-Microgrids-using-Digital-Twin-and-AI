import sys
import os
import json
import joblib
import paho.mqtt.client as mqtt
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, date, timedelta
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Font

# =============================================================================
# 1. SETUP & PATHS
# =============================================================================
EXCEL_FILE_PATH = r"c:\..............................."
ML_MODEL_PATH = r"C:\................................."
PF_PYTHON_PATH = r"C:\................................"

# โหลด ML Model
try:
    ml_voltage_model = joblib.load(ML_MODEL_PATH)
    print("โหลดโมเดล ML สำเร็จ!")
except Exception as e:
    print(f"ไม่พบไฟล์โมเดล ML หรือเกิดข้อผิดพลาด: {e}")

# เพิ่ม Path สำหรับ PowerFactory
if PF_PYTHON_PATH not in sys.path:
    sys.path.append(PF_PYTHON_PATH)

import powerfactory as pf  # type: ignore

# =============================================================================
# 2. POWERFACTORY SIMULATION CLASS
# =============================================================================
class PowerFactorySim:
    def __init__(self, folder_name='', project_name='Project', study_case_name='Study Case'):
        self.app = pf.GetApplication()
        self.project = self.app.ActivateProject(os.path.join(folder_name, project_name))
        study_case_folder = self.app.GetProjectFolder('study')
        study_case = study_case_folder.GetContents(study_case_name + '.IntCase')[0]
        self.study_case = study_case
        self.study_case.Activate()
   
    def set_al_loads_pq(self, p_load, q_load):   # ตั้งค่า P/Q ให้ทุกโหลด
        loads = self.app.GetCalcRelevantObjects('*.ElmLod')
        for load in loads:
            if isinstance(p_load, dict):
                load.plini = p_load.get(load.loc_name, load.plini)
            else:
                load.plini = p_load

            if isinstance(q_load, dict):
                load.qlini = q_load.get(load.loc_name, load.qlini)
            else:
                load.qlini = q_load

    def toggle_out_of_service(self, elm_name):   # out of service 
        elms = self.app.GetCalcRelevantObjects('*.ElmLod')
        if not elms:
            print("ไม่พบโหลดใด ๆ ในระบบ")
            return

        target = None
        for elm in elms:
            if elm.loc_name.lower() == elm_name.lower():  
                target = elm
                break

        if target is None:
            print(f"ไม่พบ element ชื่อ {elm_name}")
            return

        old_state = target.outserv
        target.outserv = 1 - old_state
        state_text = "Out of Service" if target.outserv else "In Service"
        print(f"{target.loc_name} ({target.GetClassName()}) → {state_text}")

    def set_pv_active_power(self, pv_name, p_mw):
        target_obj = None   
        pv_objs = self.app.GetCalcRelevantObjects(f"*{pv_name}.ElmPvsys")
        target_obj = next((p for p in pv_objs if p.loc_name.lower() == pv_name.lower()), None)
        
        if target_obj is None:
            gen_objs = self.app.GetCalcRelevantObjects(f"*{pv_name}.ElmGenstat")
            target_obj = next((g for g in gen_objs if g.loc_name.lower() == pv_name.lower()), None)
            
        if target_obj is None:
            raise ValueError(f"Error: ไม่พบอุปกรณ์ PV ชื่อ '{pv_name}' (หาทั้ง ElmPvsys และ ElmGenstat แล้ว)")
        
        if target_obj.outserv == 1:
            print(f"Warning: PV '{pv_name}' ถูกปลดวงจรอยู่ (Out of Service) ค่าที่ตั้งใหม่อาจไม่มีผลในการคำนวณ")

        try:
            val_to_set = float(p_mw) 
            target_obj.SetAttribute('pgini', val_to_set)
            return True
        except Exception as e:
            print(f"Error setting value: {e}")
            return False

    def set_switch_status(self, switch_name, status):
        # status: 1 = Close (On/Connect), 0 = Open (Off/Disconnect)
        switches = self.app.GetCalcRelevantObjects('*.ElmCoup')
        target_switch = next((s for s in switches if s.loc_name.lower() == switch_name.lower()), None)
        if target_switch:
            target_switch.on_off = int(status) # 1=Close, 0=Open
        return True
    
    def set_battery_power(self, bess_name, p_mw, q_mvar=0):
        bess_objs = self.app.GetCalcRelevantObjects(f"*{bess_name}.ElmGenstat")
        if not bess_objs:
             bess_objs = self.app.GetCalcRelevantObjects(f"*{bess_name}.ElmBess")
             
        bess = next((b for b in bess_objs if b.loc_name.lower() == bess_name.lower()), None)
        
        if bess is None:
            print(f"Error: ไม่พบแบตเตอรี่ชื่อ {bess_name}")
            return

        try:
            # Active Power (pgini): + จ่าย, - ชาร์จ
            bess.SetAttribute('pgini', float(p_mw))
            # Reactive Power (qgini): + จ่าย Q, - ดูด Q
            bess.SetAttribute('qgini', float(q_mvar))
        except Exception as e:
            print(f"Error setting BESS values: {e}")

    def prepare_loadflow(self, ldf_mode='balanced'):
        modes = {'balanced': 0, 'unbalanced': 1, 'dc': 2}
        self.ldf = self.app.GetFromStudyCase('ComLdf')
        self.ldf.iopt_net = modes[ldf_mode]
    
    def run_loadflow_with_pf(self, bus_name):
        ldf = self.app.GetFromStudyCase('ComLdf')
        if ldf is None:
            raise RuntimeError("Cannot find Load Flow command (ComLdf)")

        result = ldf.Execute()
        if result != 0:
            print("⚠️ Load flow execution returned non-zero result")

        bus = next((b for b in self.app.GetCalcRelevantObjects('*.ElmTerm')
                    if b.loc_name.lower() == bus_name.lower()), None)
        if bus is None:
            raise ValueError(f"ไม่พบบัสชื่อ {bus_name}")

        v_phase_pu = bus.GetAttribute('m:u')
        v_base = bus.GetAttribute('uknom')
        v_ll_kv = v_phase_pu * v_base
        return v_ll_kv

    def get_line_pq(self, line_name):
        line = next((l for l in self.app.GetCalcRelevantObjects('*.ElmLne')
                    if l.loc_name.lower() == line_name.lower()), None)
        if line is None:
            raise ValueError(f"ไม่พบสายส่งชื่อ {line_name}")

        if not line.GetAttribute('m:u1'):
            raise RuntimeError("ต้องรัน load flow ก่อน")

        results = line.GetResults()
        if not results:
            raise RuntimeError("ไม่มีผลลัพธ์ Load Flow ของสายนี้")

        res = results[0]
        pq = {
            'P_from': res.GetAttribute('m:P1'),  # MW
            'Q_from': res.GetAttribute('m:Q1'),  # MVar
            'P_to': res.GetAttribute('m:P2'),    # MW
            'Q_to': res.GetAttribute('m:Q2')     # MVar
        }
        return pq

    def get_line_flow(self, line_name):
        line = self.app.GetCalcRelevantObjects(f"{line_name}.ElmLne") 
        if not line:
            print(f"Error: ไม่พบสายส่งชื่อ '{line_name}' หรือสายส่งนี้ไม่ได้ถูกใช้งาน (not relevant).")
            return None
            
        line = line[0]
        if line.outserv == 1:
            print(f"Warning: สายส่ง '{line_name}' อยู่ในสถานะ Out of Service.")
            
        try:
            p2 = line.GetAttribute("m:P:bus2")
            q2 = line.GetAttribute("m:Q:bus2")
            S = (p2**2 + q2**2)**0.5
            PF = p2 / S if S != 0 else 0   
            return PF
        except Exception as e:
            print(f"Error reading attributes for line '{line_name}': {e}")
            print("โปรดตรวจสอบว่าคุณได้รัน Load Flow (ComLdf) แล้วหรือยัง?")
            return 0


# =============================================================================
# 3. HELPER FUNCTIONS
# =============================================================================
def calculate_ems_logic(hour, load_mw, pv_mw, soc, voltage_bus):
    global reserved_batt_power, MAX_POWER_Charge

    net_load = load_mw - (pv_mw / 1000)
    batt_cmd = 0.0 
    SOC_MAX = 0.95
    SOC_MIN = 0.05
    
    # --- หัวใจสำคัญที่เพิ่มเข้ามา: คำนวณลิมิตพลังงาน ---
    # 1. พลังงานที่จ่ายได้จริงก่อนจะถึง SOC_MIN (MWh)
    available_discharge_energy = max(0.0, (soc - SOC_MIN) * BATT_CAPACITY_MWh)
    # กำลังไฟฟ้าสูงสุดที่จ่ายได้ใน 1 ชั่วโมงโดยไม่ให้ SOC ร่วงต่ำกว่า 5% (MW)
    max_discharge_power = available_discharge_energy / 1.0 
    
    # 2. พลังงานที่ชาร์จได้จริงก่อนจะถึง SOC_MAX (MWh)
    available_charge_energy = max(0.0, (SOC_MAX - soc) * BATT_CAPACITY_MWh)
    # กำลังไฟฟ้าสูงสุดที่รับชาร์จได้ใน 1 ชั่วโมงโดยไม่เกิน 95% (MW)
    max_charge_power = available_charge_energy / 1.0

    if 9 <= hour < 22:  
        if voltage_bus < 20.9:
            # จ่ายไฟก็ต่อเมื่อมีพลังงานเหลือให้จ่ายจริงๆ
            if available_discharge_energy > 0:
                desired_power = reserved_batt_power if reserved_batt_power > 0 else MAX_POWER_MW
                # จำเป็นต้องใช้ min() เพื่อจำกัดไม่ให้จ่ายเกินความจุที่เหลือ
                batt_cmd = min(desired_power, max_discharge_power)
            else:
                batt_cmd = 0.0
        else:
            excess = abs(net_load) if net_load < 0 else 0
            # ชาร์จไฟก็ต่อเมื่อยังมีพื้นที่เหลือ
            if available_charge_energy > 0 and excess > 0:
                desired_charge = min(excess, MAX_POWER_MW)
                batt_cmd = -min(desired_charge, max_charge_power)
            else:
                batt_cmd = 0.0
    else:
        # ช่วง Off-peak ชาร์จแบตเก็บไว้ แต่ไม่ให้เกินพื้นที่แบตที่เหลือ
        if available_charge_energy > 0:
            batt_cmd = -min(MAX_POWER_Charge, max_charge_power)
        else:
            batt_cmd = 0.0

    # คำนวณ SOC ใหม่
    energy_change_mwh = batt_cmd * 1.0 
    new_soc = soc - (energy_change_mwh / BATT_CAPACITY_MWh)
    
    # Clamping ป้องกัน Error ทศนิยม
    new_soc = max(0.0, min(1.0, new_soc))
    
    return batt_cmd, new_soc

def plan_daily_battery_quota(current_soc, forecast_loads, forecast_pvs, start_hour=9):
    global reserved_batt_power
    drop_count = 0
    
    for h in range(len(forecast_loads)):
        load = forecast_loads[h] * 1000
        pv = forecast_pvs[h]
        hour = start_hour + h
        
        pred_v = ml_voltage_model.predict([[load, pv, hour]])[0]
        
        if pred_v < 20.9:
            drop_count += 1
            
    if drop_count > 0:
        available_energy_mwh = (current_soc - 0.05) * BATT_CAPACITY_MWh
        power_quota = available_energy_mwh / drop_count
        reserved_batt_power = min(power_quota, MAX_POWER_MW)
    else:
        reserved_batt_power = 0.0
        
    print(f"\n[ML Planning] พยากรณ์พบแรงดันตก {drop_count} ชั่วโมง")
    print(f"[ML Planning] จัดสรรโควต้าแบตเตอรี่ไว้ที่: {reserved_batt_power:.3f} MW ต่อการจ่าย 1 ครั้ง\n")
    
def Buildgraph1(current_dataframe):
    if not os.path.exists('temp_images'):
        os.makedirs('temp_images')

    df_plot = pd.DataFrame({
        'Hour': hours,
        'Load': Load_graph,
        'PV': PV_graph,
        'SOC': SOC_graph,
        'Voltage': voltage_graph,
        'Batt': batt_graph
    })

    # Graph 1: Power & SOC
    fig1, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(df_plot['Hour'], df_plot['Load'], label='Load (MW)', color='blue')
    ax1.plot(df_plot['Hour'], df_plot['PV'], label='PV (MW)', color='orange')
    ax1.plot(df_plot['Hour'], df_plot['Load'] - df_plot['PV'] - df_plot['Batt'], label='Net Load (MW)', color='red', linewidth=2)
    
    ax1.grid(True, alpha=0.3)
    ax1.set_ylabel('Power (MW)')    
    ax1.legend(loc='upper left')
    
    ax2 = ax1.twinx()
    ax2.plot(df_plot['Hour'], df_plot['SOC'], label='SOC (%)', color='green', linestyle='--')
    ax2.set_ylabel('SOC (%)')
    ax2.set_ylim(0, 110)
    ax2.legend(loc='upper right')
    
    plt.title(f'Daily Summary: {Day_s}')
    
    graph1_path = 'temp_images/daily_summary.png'
    plt.savefig(graph1_path, bbox_inches='tight', dpi=100)
    plt.close()

    # Graph 2: Voltage
    fig2, ax3 = plt.subplots(figsize=(10, 3))
    ax3.plot(df_plot['Hour'], df_plot['Voltage'], label='Bus Voltage (kV)', color='purple', marker='x')
    ax3.set_ylabel('Voltage (kV)')
    ax3.set_title('Daily Voltage Profile')
    ax3.grid(True, alpha=0.3)
    
    graph2_path = 'temp_images/voltage_summary.png'
    plt.savefig(graph2_path, bbox_inches='tight', dpi=100)
    plt.close()
    
    # 2.1 บันทึก Data (Sheet1) ก่อน
    with pd.ExcelWriter(EXCEL_FILE_PATH, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
        current_dataframe.to_excel(writer, sheet_name='Sheet1', index=False)

    # 2.2 บันทึกกราฟ (Daily_Graph)
    wb = load_workbook(EXCEL_FILE_PATH)
    
    if 'Daily_Graph' not in wb.sheetnames:
        ws = wb.create_sheet('Daily_Graph')
    else:
        ws = wb['Daily_Graph']

    row_offset = (j - 1) * 40
    start_row = 2 + row_offset
    
    # เขียนหัวข้อวันที่
    header_cell = ws.cell(row=start_row, column=2) # Column B
    header_cell.value = f"Day {j}: Summary Report for {Day_s}"
    header_cell.font = Font(bold=True, size=14, color="0000FF")

    img1 = OpenpyxlImage(graph1_path)
    ws.add_image(img1, f'B{start_row + 2}')

    img2 = OpenpyxlImage(graph2_path)
    ws.add_image(img2, f'B{start_row + 22}')

    wb.save(EXCEL_FILE_PATH)  
    print(f"บันทึกกราฟวันที่ {j} เรียบร้อยแล้ว")


# =============================================================================
# 4. MQTT CALLBACKS
# =============================================================================
MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC = "loaddata"

def on_connect(client, userdata, flags, rc, properties=None): 
    if rc == 0:
        print(f"Connected with result code {rc}")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    global i, Day_s, j, current_soc, l, m
    global yesterday_load, yesterday_pv
    global reserved_batt_power
    
    received_string = msg.payload.decode()
    data = json.loads(received_string)
    p_value = data['load_P']
    q_value = data['load_Q']
    p_all = p_value * 15
    pv_value = data['pv_P']
    
    if i == 9:
        if j == 1:
            forecast_loads = [p_all * 1.1, p_all * 1.2, p_all * 1.3] * 4 + [p_all] 
            forecast_pvs = [pv_value, pv_value * 1.2, pv_value * 0.8] * 4 + [0.0]
        else:
            forecast_loads = yesterday_load[9:22]
            forecast_pvs = yesterday_pv[9:22]
              
        plan_daily_battery_quota(current_soc, forecast_loads, forecast_pvs, start_hour=9)

    for k in range(0, 16, 1):
        if k < len(loadname):
            p_load = {loadname[k]: p_value}     
            q_load = {loadname[k]: q_value}
            sim.set_al_loads_pq(p_load, q_load)
        if k < len(PVname):
            sim.set_pv_active_power(PVname[k], pv_value)
            
    for k in range(len(Battname)):
        sim.set_battery_power(Battname[k], 0.0)   

    sim.prepare_loadflow('balanced')
    voltage_BUS = sim.run_loadflow_with_pf('one')
    powerfac = sim.get_line_flow('Line(12)')
    
    voltage_graph[i] = voltage_BUS

    # -------------------------------------------------------------------------
    # EMS Logic Execution
    # -------------------------------------------------------------------------
    batt_cmd, next_soc = calculate_ems_logic(i, p_all, pv_value, current_soc, voltage_BUS)
    current_soc = next_soc
    
    power_per_batt = batt_cmd 
    for k in range(len(Battname)): 
        sim.set_battery_power(Battname[k], power_per_batt)
        
    batt_graph[i] = power_per_batt
    print(f"\n--- Hour {i}:00 ---")
    print(f"Status: Load={p_all:.3f} MW, PV={pv_value*2:.3f} kW, SOC_Old={current_soc*100:.1f}%")
    print(f"Decision: Battery Power = {power_per_batt:.3f} MW (SOC -> {next_soc*100:.1f}%)")

    if (voltage_BUS < 20.9) or (power_per_batt > 0):
        sim.prepare_loadflow('balanced')
        voltage_BUS = sim.run_loadflow_with_pf('one')
        powerfac = sim.get_line_flow('Line(12)')
        voltage_graph[i] = voltage_BUS
    
    PV_graph[i] = pv_value * 2 / 1000 
    Load_graph[i] = p_all

    if 9 <= i < 22: 
        Load_perhour_renew[i] = (p_all*1000 - pv_value*2 - power_per_batt*1000) * Onpeak 
        Load_perhour[i] = p_all * Onpeak * 1000
    else:
        Load_perhour_renew[i] = (p_all*1000 - pv_value*2 - power_per_batt*1000) * Offpeak 
        Load_perhour[i] = p_all * Offpeak * 1000
    
    SOC_graph[i] = next_soc * 100

    df_existing.loc[i, f"Bus:{Day_s}"] = voltage_BUS
    df_existing.loc[i, f"PF:{Day_s}"] = powerfac
    print(f"date: {Day_s} time: {i:.2f}-{i+1:.2f} -->  Last = {voltage_BUS:.3f} kV ,  PF = {powerfac:.3f}")
    
    Load_perday_renew[l] = sum(Load_perhour_renew)
    Load_perday[l] = sum(Load_perhour)
    PV_day[m] = pv_value * 2
    
    m += 1
    i += 1
    
    # Check end of day
    if i == 24:
        Buildgraph1(df_existing)
        yesterday_load = Load_graph.copy()
        yesterday_pv = PV_graph.copy()

        # Yearly Summary check
        if Day_s.month == 1 and Day_s.day == 2:
            Saving = (sum(Load_perday)) - (sum(Load_perday_renew))
            Payback_period = cost / Saving if Saving != 0 else 0
            LCOE = cost / (sum(PV_day)) if sum(PV_day) != 0 else 0
            
            print(f"--------------------------------------------------")
            print(f"Date Summary: {Day_s}")
            print(f"Saving = {Saving:.2f} THB")
            print(f"Payback Period = {Payback_period:.2f} years")
            print(f"LCOE = {LCOE:.2f} THB/MWh")
            print(f"--------------------------------------------------")
            
            Load_perday_renew.fill(0)
            Load_perday.fill(0)
            l = -1
            m = 0
            
        Day_s = start_day + timedelta(days=j)
        Load_perhour_renew.fill(0)
        Load_perhour.fill(0)
        SOC_graph.fill(0)
        PV_graph.fill(0)
        Load_graph.fill(0)
        voltage_graph.fill(0)
        l += 1
        j += 1
        i = 0   


# =============================================================================
# 5. GLOBAL VARIABLES INITIALIZATION & MAIN EXECUTION
# =============================================================================
if __name__ == "__main__":
    # DataFrame
    try:
        df_existing = pd.read_excel(EXCEL_FILE_PATH, engine="openpyxl")
    except Exception as e:
        print(f"ไม่สามารถโหลดไฟล์ Excel ได้: {e}")
        df_existing = pd.DataFrame()

    # Time & Iteration variables
    start_day = date(2025, 1, 1)
    Day_s = start_day
    i, l, m = 0, 0, 0
    j = 1

    # System Constants
    BATT_CAPACITY_MWh = 2 
    MAX_POWER_MW = 0.5
    MAX_POWER_Charge = 0.2
    Onpeak = 4.1839
    Offpeak = 2.6037
    service_charge = 312.24
    cost = 380000000

    # Current States
    current_soc = 1           
    reserved_batt_power = 0.0

    # Lists
    loadname = ['LD1','LD2','LD3','LD4','LD5','LD6','LD7','LD8','LD9','LD10','LD11','LD12','LD13','LD14','LD15']
    PVname = ['PV1','PV2']
    Battname = ['Bat1','Bat2','Bat3','Bat4','Bat5']

    # Arrays for graphing and calculations
    hours = np.arange(24)
    SOC_graph = np.zeros(24)
    PV_graph = np.zeros(24)
    Load_graph = np.zeros(24)
    voltage_graph = np.zeros(24)
    batt_graph = np.zeros(24)
    Load_perhour = np.zeros(24)
    Load_perhour_renew = np.zeros(24)
    yesterday_load = np.zeros(24)
    yesterday_pv = np.zeros(24)
    Load_perday = np.zeros(366)
    Load_perday_renew = np.zeros(366)
    PV_day = np.zeros(366)

    # Initialize PowerFactory Simulation
    sim = PowerFactorySim(folder_name='', project_name='I', study_case_name='Loadflow1')

    # Initialize MQTT Client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "receiver-script")
    client.on_connect = on_connect 
    client.on_message = on_message 
    client.connect(MQTT_BROKER, 1883)

    print("Subscriber is running, waiting for messages...")
    client.loop_forever()