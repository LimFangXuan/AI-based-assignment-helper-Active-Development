"""生成一对推送用的 VAPID 密钥：python generate_vapid_keys.py

把输出的两行复制到 .env（或托管平台的环境变量）里。生成之后不要再换：换了以后，所有设备都要重新开启推送。
私钥等同于密码，不要提交到 git，也不要发给别人。
"""
from app.services import push

if __name__ == "__main__":
    private_key, public_key = push._generate()
    print(f"VAPID_PRIVATE_KEY={private_key}")
    print(f"VAPID_PUBLIC_KEY={public_key}")
