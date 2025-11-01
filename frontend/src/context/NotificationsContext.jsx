import { createContext, useCallback, useContext, useMemo, useState } from "react";

const NotificationsContext = createContext(null);

const TYPE_STYLES = {
        info: {
                background: "#e0f2ff",
                border: "1px solid #64b5f6",
                color: "#0b5394",
        },
        success: {
                background: "#e6f4ea",
                border: "1px solid #52b788",
                color: "#1b4332",
        },
        warning: {
                background: "#fff8e1",
                border: "1px solid #f6c26b",
                color: "#7c4a03",
        },
        error: {
                background: "#fdecea",
                border: "1px solid #f28b82",
                color: "#b71c1c",
        },
};

function NotificationStack({ notifications, onDismiss, placement }) {
        if (!notifications.length) {
                return null;
        }

        const baseStyle =
                placement === "inline"
                        ? {
                                  position: "fixed",
                                  top: "4rem",
                                  left: "50%",
                                  transform: "translateX(-50%)",
                                  zIndex: 1000,
                                  width: "min(600px, calc(100% - 2rem))",
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: "0.75rem",
                          }
                        : {
                                  position: "fixed",
                                  top: "1.5rem",
                                  right: "1.5rem",
                                  zIndex: 1000,
                                  width: "min(320px, calc(100% - 2rem))",
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: "0.75rem",
                          };

        return (
                <div style={baseStyle}>
                        {notifications.map((notification) => {
                                const { id, type, message } = notification;
                                const style = {
                                        padding: "0.75rem 1rem",
                                        borderRadius: "0.5rem",
                                        boxShadow: "0 4px 16px rgba(0, 0, 0, 0.08)",
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "flex-start",
                                        gap: "1rem",
                                        fontSize: "0.95rem",
                                        ...(TYPE_STYLES[type] || TYPE_STYLES.info),
                                };

                                return (
                                        <div key={id} style={style} role="alert">
                                                <span style={{ flex: 1, lineHeight: 1.4 }}>{message}</span>
                                                <button
                                                        type="button"
                                                        onClick={() => onDismiss(id)}
                                                        style={{
                                                                border: "none",
                                                                background: "transparent",
                                                                color: "inherit",
                                                                cursor: "pointer",
                                                                fontWeight: 600,
                                                        }}
                                                >
                                                        ×
                                                </button>
                                        </div>
                                );
                        })}
                </div>
        );
}

export function NotificationProvider({ children }) {
        const [notifications, setNotifications] = useState([]);

        const dismiss = useCallback((id) => {
                setNotifications((prev) => prev.filter((item) => item.id !== id));
        }, []);

        const notify = useCallback(
                ({ type = "info", message, placement = "toast", autoDismiss = placement === "toast" ? 6000 : null }) => {
                        if (!message) {
                                return null;
                        }

                        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
                        const notification = { id, type, message, placement };
                        setNotifications((prev) => [...prev, notification]);

                        if (autoDismiss !== null) {
                                window.setTimeout(() => {
                                        dismiss(id);
                                }, autoDismiss);
                        }

                        return notification;
                },
                [dismiss],
        );

        const contextValue = useMemo(
                () => ({
                        notify,
                        dismiss,
                }),
                [notify, dismiss],
        );

        const toastNotifications = notifications.filter((n) => n.placement === "toast");
        const inlineNotifications = notifications.filter((n) => n.placement === "inline");

        return (
                <NotificationsContext.Provider value={contextValue}>
                        {children}
                        <NotificationStack
                                notifications={toastNotifications}
                                onDismiss={dismiss}
                                placement="toast"
                        />
                        <NotificationStack
                                notifications={inlineNotifications}
                                onDismiss={dismiss}
                                placement="inline"
                        />
                </NotificationsContext.Provider>
        );
}

export function useNotifications() {
        const context = useContext(NotificationsContext);
        if (!context) {
                throw new Error("useNotifications must be used within a NotificationProvider");
        }
        return context;
}
