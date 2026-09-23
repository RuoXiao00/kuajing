import { Navigate } from "react-router-dom";
import Tuijian from "../compoment/tuijain/Tuijian";
import Remeng from "../compoment/remeng/Remeng";
import Zhishiku from "../compoment/zhishiku/Zhishiku";
import Tupian from "../compoment/tupian/Tupian";
import Settings from "../compoment/shezhi/Settings";
import AdminDashboard from "../compoment/guanli/AdminDashboard";
import DefaultHome from "./DefaultHome";

// 路由表是 URL 到 React 元素的映射。它只描述“显示哪个组件”，
// 不负责启动服务器，也不会在数组声明时发起知识库请求。
// 使用具名常量导出，Vite Fast Refresh 才能稳定识别该模块不是匿名组件。
const routers = [
  {
    path: "/",
    element: <DefaultHome />
  },
  {
    path: "/tuijian",
    element: <Tuijian />
  },
  {
    path: "/remeng",
    element: <Remeng />
  },
  {
    path: "/zhishiku",
    element: <Zhishiku />
  },
  {
    path: "/tupian",
    element: <Tupian />
  },
  {
    path: "/settings",
    element: <Settings />
  },
  {
    path: "/admin",
    element: <AdminDashboard />
  },
  {
    // 已移除功能的旧书签或无效地址回到首页，避免显示空白内容。
    path: "*",
    element: <Navigate to="/tuijian" replace />
  }
];

export default routers;
