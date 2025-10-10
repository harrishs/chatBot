/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import api from "../api/axios";

const AuthContext = createContext({
        user: null,
        initializing: true,
        login: async () => {},
        logout: async () => {},
        refreshSession: async () => {},
});

export function AuthProvider({ children }) {
        const [user, setUser] = useState(null);
        const [initializing, setInitializing] = useState(true);

        const fetchSession = useCallback(async () => {
                try {
                        const response = await api.get("/auth/session/");
                        setUser(response.data);
                        return response.data;
                } catch (error) {
                        setUser(null);
                        throw error;
                }
        }, []);

        const ensureCsrfToken = useCallback(async () => {
                try {
                        await api.get("/csrf/");
                } catch (error) {
                        // Failing to fetch the CSRF token should not break auth initialisation.
                        console.warn("Failed to fetch CSRF token", error);
                }
        }, []);

        useEffect(() => {
                let active = true;

                (async () => {
                        await ensureCsrfToken();
                        try {
                                await fetchSession();
                        } catch (error) {
                                console.error("Failed to refresh session", error);
                                if (active) {
                                        setUser(null);
                                }
                        } finally {
                                if (active) {
                                        setInitializing(false);
                                }
                        }
                })();

                return () => {
                        active = false;
                };
        }, [ensureCsrfToken, fetchSession]);

        const login = useCallback(
                async (username, password) => {
                        await ensureCsrfToken();
                        try {
                                await api.post("/login/", { username, password });
                                await ensureCsrfToken();
                                await fetchSession();
                        } catch (error) {
                                setUser(null);
                                throw error;
                        }
                },
                [ensureCsrfToken, fetchSession],
        );

        const logout = useCallback(async () => {
                await ensureCsrfToken();
                try {
                        await api.post("/logout/");
                } finally {
                        setUser(null);
                }
        }, [ensureCsrfToken]);

        const value = useMemo(
                () => ({
                        user,
                        initializing,
                        login,
                        logout,
                        refreshSession: fetchSession,
                }),
                [user, initializing, login, logout, fetchSession],
        );

        return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
        return useContext(AuthContext);
}
