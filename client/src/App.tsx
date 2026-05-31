import { BrowserRouter, Routes, Route } from 'react-router-dom'
import MatchList from './pages/MatchList'
import MatchDetail from './pages/MatchDetail'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MatchList />} />
        <Route path="/matches/:id" element={<MatchDetail />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
