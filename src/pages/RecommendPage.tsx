/**
 * 页面：内容分析与方案推荐
 */

import React from 'react';
import { Card, Typography } from 'antd';

const { Title, Text } = Typography;


const RecommendPage: React.FC = () => {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={2}>方案推荐</Title>
        <Text type="secondary">根据分析结果推荐最适合的剪辑方案</Text>
      </div>

      <Card>
        <Text>方案推荐功能开发中...</Text>
      </Card>
    </div>
  );
};

export default RecommendPage;
