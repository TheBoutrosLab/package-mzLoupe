import { createRoot } from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import "@mantine/core/styles.css";
import "mantine-datatable/styles.css";
import "./style.css";
import { Application } from "./Application";
import "./setup.css";

// Supply a shared theme to both project setup and the inspection workspace.
createRoot(document.getElementById("root")!).render(
  <MantineProvider
    theme={{
      primaryColor: "teal",
      primaryShade: 9,
      fontFamily: "Inter, system-ui, sans-serif",
      defaultRadius: "sm"
    }}
  >
    <Application />
  </MantineProvider>
);
