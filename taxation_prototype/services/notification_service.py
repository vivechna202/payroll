"""
notification_service.py – Service layer to manage system, HR, manager, and employee notifications.
"""

import os
import uuid
import pandas as pd
from datetime import datetime
from config import DUMMY_DATA_FOLDER
from services.csv_service import read_csv, write_csv, append_row

CSV_NOTIFICATIONS = os.path.join(DUMMY_DATA_FOLDER, "notifications.csv")

def ensure_notifications_csv():
    """Ensure the notifications CSV file exists with correct columns."""
    if not os.path.exists(CSV_NOTIFICATIONS):
        os.makedirs(os.path.dirname(CSV_NOTIFICATIONS), exist_ok=True)
        pd.DataFrame(columns=[
            "notification_id", "recipient_id", "message", "type", "is_read", "timestamp", "link"
        ]).to_csv(CSV_NOTIFICATIONS, index=False)

def create_notification(recipient_id: str, message: str, notification_type: str = "Information", link: str = "") -> dict:
    """
    Create a new notification.
    recipient_id can be employee_id or 'hr'.
    notification_type can be 'Success', 'Warning', 'Information', 'Reminder'.
    """
    ensure_notifications_csv()
    nid = f"NOT-{str(uuid.uuid4())[:8].upper()}"
    
    notification = {
        "notification_id": nid,
        "recipient_id": recipient_id,
        "message": message,
        "type": notification_type,
        "is_read": "False",
        "timestamp": datetime.now().isoformat(),
        "link": link
    }
    append_row(CSV_NOTIFICATIONS, notification)
    return notification

def get_notifications(recipient_id: str, include_read: bool = True) -> list[dict]:
    """Retrieve notifications for a specific employee or role (e.g. 'hr')."""
    ensure_notifications_csv()
    df = read_csv(CSV_NOTIFICATIONS)
    if df.empty:
        return []
        
    # Check both specific employee_id and 'hr' role if recipient is HR
    if recipient_id == "hr":
        df = df[df["recipient_id"] == "hr"]
    else:
        # Check if recipient_id matches exactly
        df = df[df["recipient_id"] == recipient_id]
        
    if not include_read:
        df = df[df["is_read"] == "False"]
        
    # Sort by timestamp descending
    if not df.empty and "timestamp" in df.columns:
        df = df.sort_values(by="timestamp", ascending=False)
        
    return df.to_dict(orient="records")

def get_unread_count(recipient_id: str) -> int:
    """Get count of unread notifications."""
    return len(get_notifications(recipient_id, include_read=False))

def mark_as_read(notification_id: str) -> bool:
    """Mark a specific notification as read."""
    ensure_notifications_csv()
    df = read_csv(CSV_NOTIFICATIONS)
    if df.empty or "notification_id" not in df.columns:
        return False
        
    mask = df["notification_id"] == notification_id
    if not mask.any():
        return False
        
    df.loc[mask, "is_read"] = "True"
    write_csv(CSV_NOTIFICATIONS, df)
    return True

def mark_all_as_read(recipient_id: str) -> bool:
    """Mark all notifications for a recipient as read."""
    ensure_notifications_csv()
    df = read_csv(CSV_NOTIFICATIONS)
    if df.empty or "recipient_id" not in df.columns:
        return False
        
    mask = df["recipient_id"] == recipient_id
    if not mask.any():
        return False
        
    df.loc[mask, "is_read"] = "True"
    write_csv(CSV_NOTIFICATIONS, df)
    return True

def get_email_template(notification_type: str, recipient_name: str, message: str) -> str:
    """Returns a placeholder HTML email-ready notification template."""
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 5px; padding: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
                <div style="background-color: #764ba2; color: #fff; padding: 15px; text-align: center; border-radius: 5px 5px 0 0;">
                    <h2>TaxPro HRMS Notification</h2>
                </div>
                <div style="padding: 20px;">
                    <p>Dear {recipient_name},</p>
                    <p style="font-size: 1.1em; background-color: #f9f9f9; padding: 10px; border-left: 4px solid #764ba2;">
                        <strong>{notification_type}:</strong> {message}
                    </p>
                    <p>This is an automated message from the TaxPro HRMS Workflow Engine.</p>
                </div>
                <div style="border-top: 1px solid #eee; padding-top: 15px; font-size: 0.8em; color: #777; text-align: center;">
                    &copy; 2026 TaxPro HRMS. All rights reserved.
                </div>
            </div>
        </body>
    </html>
    """
