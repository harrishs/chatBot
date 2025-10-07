import axios from "axios";

const baseURL = import.meta.env?.VITE_API_BASE_URL || "/api";

const api = axios.create({
        baseURL,
});

api.interceptors.request.use((config) => {
	const token = localStorage.getItem("authToken");
	if (token) {
		config.headers.Authorization = `Token ${token}`;
	}
	return config;
});

export default api;
