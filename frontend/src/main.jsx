import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import Login from "./pages/Login.jsx";
import ChatBots from "./pages/ChatBots.jsx";

createRoot(document.getElementById("root")).render(
	<StrictMode>
		<BrowserRouter>
			<Routes>
				<Route path="/login" element={<Login />} />
				<Route
					path="/"
					element={
						<ProtectedRoute>
							<App />
						</ProtectedRoute>
					}
				/>
				<Route
					path="/chatbots"
					element={
						<ProtectedRoute>
							<ChatBots />
						</ProtectedRoute>
					}
				/>
			</Routes>
		</BrowserRouter>
	</StrictMode>
);
