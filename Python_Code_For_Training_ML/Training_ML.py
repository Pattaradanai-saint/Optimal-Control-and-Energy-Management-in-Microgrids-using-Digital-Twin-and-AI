import os
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error

# =============================================================================
# 1. SETUP & PATHS
# =============================================================================
FOLDER_PATH = r"C:\.................."

pv_file = os.path.join(FOLDER_PATH, "PV_8760.csv")
load_file = os.path.join(FOLDER_PATH, "Load_87602.csv")
voltage_file = os.path.join(FOLDER_PATH, "Voltage_87602.csv")
model_save_path = os.path.join(FOLDER_PATH, "voltage_prediction_model.pkl")

# =============================================================================
# 2. DATA LOADING & PREPROCESSING
# =============================================================================
print("กำลังโหลดและรวมข้อมูล...")

# โหลดไฟล์ CSV
df_pv = pd.read_csv(pv_file)
df_load = pd.read_csv(load_file)
df_voltage = pd.read_csv(voltage_file)

# สร้าง DataFrame หลักและนำข้อมูลมารวมกัน
df_main = pd.DataFrame()
df_main['Load_kW'] = df_load['Load(KW)']
df_main['PV_kW'] = df_pv['power']
df_main['Voltage_kV'] = df_voltage['Voltage(V)']

# สร้างฟีเจอร์ "ชั่วโมงของวัน (0-23)" เพื่อให้โมเดลจับแพทเทิร์นเวลาได้ดีขึ้น
df_main['Hour'] = pd.to_datetime(df_load['datetime'], format='mixed', dayfirst=True).dt.hour

print("\nตัวอย่างข้อมูลที่รวมแล้ว:")
print(df_main.head())

# =============================================================================
# 3. TRAIN/TEST SPLIT
# =============================================================================
# กำหนดตัวแปรต้น (X) และตัวแปรตาม (y)
X = df_main[['Load_kW', 'PV_kW', 'Hour']] 
y = df_main['Voltage_kV'] 

# แบ่งข้อมูลสำหรับสอน (Train) 80% และทดสอบ (Test) 20%
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# =============================================================================
# 4. MODEL TRAINING
# =============================================================================
print("\nกำลังฝึกสอนโมเดล ML (Random Forest)... อาจใช้เวลาสักครู่")
model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)

# =============================================================================
# 5. EVALUATION & SAVING
# =============================================================================
# ทดสอบความแม่นยำด้วยข้อสอบ (Test Data)
predictions = model.predict(X_test)
mae = mean_absolute_error(y_test, predictions)
mse = mean_squared_error(y_test, predictions)

print("\nฝึกสอนเสร็จสิ้น!")
print(f"ค่าความคลาดเคลื่อนเฉลี่ย (MAE): {mae:.4f} kV") 
print(f"แปลว่า: โมเดลทายแรงดันคลาดเคลื่อนจากความจริงโดยเฉลี่ยแค่ {mae:.4f} kV เท่านั้น")

# บันทึกเป็นไฟล์ .pkl เพื่อนำไปใช้งานต่อในโปรแกรมหลัก
joblib.dump(model, model_save_path)
print(f"\nบันทึกโมเดลสำเร็จที่: {model_save_path}")

# Checking the model by plotting actual vs predicted voltage for a sample of test data
import matplotlib.pyplot as plt

# 1. สุ่มหยิบข้อมูลในส่วนของ Test Data มาสัก 100 ชั่วโมงเพื่อวาดกราฟ
# (X_test และ y_test มีอยู่ในโค้ดเดิมของคุณแล้ว)
X_sample = X_test.head(100)
y_actual = y_test.head(100).values
y_pred = model.predict(X_sample)

# 2. ตั้งค่าการวาดกราฟ
plt.figure(figsize=(12, 5))
plt.plot(y_actual, label='Actual Voltage (แรงดันจริง)', color='blue', marker='o', markersize=3)
plt.plot(y_pred, label='Predicted Voltage (ML ทาย)', color='red', linestyle='--', marker='x', markersize=3)

# 3. ตกแต่งกราฟ
plt.axhline(y=21.0, color='green', linestyle=':', label='Threshold (21 kV)')
plt.title('ML Model Validation: Actual vs Predicted Voltage')
plt.xlabel('Time Step (Hours)')
plt.ylabel('Voltage (kV)')
plt.legend()
plt.grid(True, alpha=0.3)

# 4. แสดงกราฟ
plt.show()