import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconCheck } from "@tabler/icons-react";
import { createElement } from "react";
import { errorMessage } from "./errors";

export function notifySuccess(message: string, title?: string) {
  notifications.show({
    color: "gpGreen",
    title,
    message,
    icon: createElement(IconCheck, { size: 16 }),
    autoClose: 3500,
  });
}

export function notifyError(err: unknown, title = "Couldn't complete that") {
  notifications.show({
    color: "red",
    title,
    message: errorMessage(err),
    icon: createElement(IconAlertTriangle, { size: 16 }),
    autoClose: 6000,
  });
}
