import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Main } from "./pages/Main";
import { Detail } from "./pages/Detail";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Main />} />
        <Route path="/character/:name" element={<Detail />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
