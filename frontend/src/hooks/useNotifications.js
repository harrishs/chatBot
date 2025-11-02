import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export const NOTIFICATION_TYPE_COLORS = {
        info: "#2B6CB0",
        success: "#2F855A",
        warning: "#B7791F",
        error: "#C53030",
};

const containerStyle = {
        position: "fixed",
        top: "1rem",
        right: "1rem",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        maxWidth: "min(90vw, 320px)",
};

const baseNotificationStyle = {
        backgroundColor: "#fff",
        borderRadius: "8px",
        boxShadow: "0 8px 20px rgba(0, 0, 0, 0.12)",
        padding: "0.75rem 1rem",
        display: "flex",
        alignItems: "flex-start",
        gap: "0.75rem",
        border: "1px solid rgba(0, 0, 0, 0.08)",
};

const messageStyle = {
        margin: 0,
        color: "#1A202C",
        fontSize: "0.95rem",
        lineHeight: 1.4,
        flex: 1,
};

const dismissButtonStyle = {
        appearance: "none",
        border: "none",
        background: "transparent",
        color: "#4A5568",
        cursor: "pointer",
        fontSize: "1.1rem",
        lineHeight: 1,
        padding: 0,
};

let notificationIdCounter = 0;

export function useNotifications({ autoHideDuration = 6000 } = {}) {
        const [notifications, setNotifications] = useState([]);
        const timersRef = useRef(new Map());

        const clearTimer = useCallback((id) => {
                const timers = timersRef.current;
                const timerId = timers.get(id);
                if (timerId) {
                        clearTimeout(timerId);
                        timers.delete(id);
                }
        }, []);

        const dismiss = useCallback(
                (id) => {
                        clearTimer(id);
                        setNotifications((prev) => prev.filter((item) => item.id !== id));
                },
                [clearTimer]
        );

        const notify = useCallback(
                ({ type = "info", message, autoHide } = {}) => {
                        if (!message) {
                                return null;
                        }
                        notificationIdCounter += 1;
                        const id = notificationIdCounter;
                        const notification = { id, type, message };
                        setNotifications((prev) => [...prev, notification]);

                        const resolvedDuration =
                                typeof autoHide === "number" ? autoHide : autoHideDuration;
                        if (resolvedDuration > 0) {
                                const timerId = setTimeout(() => {
                                        dismiss(id);
                                }, resolvedDuration);
                                timersRef.current.set(id, timerId);
                        }

                        return notification;
                },
                [autoHideDuration, dismiss]
        );

        useEffect(() => () => {
                timersRef.current.forEach((timerId) => {
                        clearTimeout(timerId);
                });
                timersRef.current.clear();
        }, []);

        const contextValue = useMemo(
                () => ({ notifications, notify, dismiss }),
                [notifications, notify, dismiss]
        );

        return contextValue;
}

export function Notifications({ notifications, onDismiss }) {
        if (!notifications || notifications.length === 0) {
                return null;
        }

        return (
                <div style={containerStyle} role="region" aria-live="polite">
                        {notifications.map((notification) => {
                                const { id, type, message } = notification;
                                const accentColor =
                                        NOTIFICATION_TYPE_COLORS[type] || NOTIFICATION_TYPE_COLORS.info;

                                return (
                                        <div
                                                key={id}
                                                style={{
                                                        ...baseNotificationStyle,
                                                        borderLeft: `4px solid ${accentColor}`,
                                                }}
                                        >
                                                <p style={messageStyle}>{message}</p>
                                                <button
                                                        type="button"
                                                        onClick={() => onDismiss?.(id)}
                                                        style={dismissButtonStyle}
                                                        aria-label="Dismiss notification"
                                                >
                                                        ×
                                                </button>
                                        </div>
                                );
                        })}
                </div>
        );
}
