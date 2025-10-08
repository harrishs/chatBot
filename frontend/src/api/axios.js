import axios from "axios";

const baseURL = import.meta.env?.VITE_API_BASE_URL || "/api";

const api = axios.create({
        baseURL,
        withCredentials: true,
        xsrfCookieName: "csrftoken",
        xsrfHeaderName: "X-CSRFToken",
});

export default api;
