import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";
import { Layout } from "./components/Layout";
import { Onboarding } from "./routes/Onboarding";
import { Degree } from "./routes/Degree";
import { Radar } from "./routes/Radar";
import { Counselor } from "./routes/Counselor";
import { Agent } from "./routes/Agent";
import { loadSession } from "./lib/session";
import "./styles/tokens.css";
import "./styles/app.css";

// No home screen of its own: Degree once there's a profile, onboarding before that.
function Home() {
  return <Navigate to={loadSession().profile ? "/degree" : "/onboarding"} replace />;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/onboarding", element: <Onboarding /> },
      { path: "/degree", element: <Degree /> },
      { path: "/radar", element: <Radar /> },
      { path: "/counselor", element: <Counselor /> },
      { path: "/agent", element: <Agent /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
