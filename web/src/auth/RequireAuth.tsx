import { type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Center, Loader } from "@mantine/core";
import { useAuth } from "./AuthProvider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const loc = useLocation();

  if (loading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (!session) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return <>{children}</>;
}
