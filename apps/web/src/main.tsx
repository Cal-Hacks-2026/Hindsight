import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Layout } from "./components/Layout";
import { Today } from "./routes/Today";
import { Onboarding } from "./routes/Onboarding";
import { Degree } from "./routes/Degree";
import { Radar } from "./routes/Radar";
import { Counselor } from "./routes/Counselor";
import { Agent } from "./routes/Agent";
import "./styles/tokens.css";
import "./styles/app.css";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Today /> },
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
