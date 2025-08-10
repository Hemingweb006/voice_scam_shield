import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import CallsList from "./CallsList";
import LiveCall from "./LiveCall";

export default function App() {
  const backend = "http://localhost:8000"; // change if needed
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CallsList backend={backend} />} />
        <Route path="/call/:sid" element={<LiveCall backend={backend} />} />
      </Routes>
    </BrowserRouter>
  );
}
